# DRC Pay — Development Log & Handoff

**Last updated:** 2026-06-13 · **Read this first to resume work.**

**Product:** a **merchant-facing** app for the DRC that lets merchants **accept mobile-money payments
across networks** (Vodacom M-Pesa, Airtel, Orange) on **rented rails (pawaPay)** as a **pure
pass-through** (we never hold funds). Customers pay by scanning the merchant's QR or dialing USSD —
**no app of their own**. Initial launch: ~40 gas stations + pop-up stores. Research is the sibling
`../drc-mvp-research/`; this repo (`drc-pay/`) is the app.

---

## TL;DR — where we are
- **Backend (`services/api`)** — fully green: ruff + mypy --strict clean, **118 tests**. Built: the
  payment spine (collect → settle → auto-refund), double-entry ledger, 10-state machine, idempotency,
  Merchant domain, 1% MDR fee model, Postgres + Alembic, the pawaPay client/rail, the **USSD channel**,
  the **signed callback receiver** (D.1) and the **reconciliation sweep** (D.2).
- **Live pawaPay sandbox PROVEN (2026-06-13):** a real cross-network payment ran end-to-end on
  `api.sandbox.pawapay.io` — Vodacom deposit → Airtel payout → fee booked — healed by polling.
- **Web UI (both sides built + verified):** the **Merchant Console** (`tooling/merchant-console`,
  password-gated) — take payments, live feed, "Run reconciliation" safety net, ledger drill-down; and
  the **Customer app** (`tooling/customer-app`, public) — scan-to-pay with an outcome toggle
  (success/decline/refund) + an operations trace, plus a **USSD dial simulator**.
- **Deploy: ready, not yet live.** One `Dockerfile` serves the API + both web apps as a single
  container, behind an optional shared password, with Postgres-URL handling and Alembic-on-start.

## ▶ NEXT GOAL: stand the live webpage up on Railway
Deploy the container to **Railway** (Hobby $5/mo) per **`docs/deploy-railway.md`**: connect the GitHub
repo (Railway builds the `Dockerfile`), add Postgres (`DRCPAY_DATABASE_URL=${{Postgres.DATABASE_URL}}`),
set the secrets (`DRCPAY_PAWAPAY_API_TOKEN`, a `DRCPAY_BASIC_AUTH_PASSWORD`), generate a public URL.
Then a real phone can scan a merchant's QR → pay → watch it land in the console. The token + dashboard
steps are the **human's** (nothing secret in the repo); I need only the public URL back, to point
pawaPay's **callbacks** at it — which closes the last Phase-E gap (real-time confirmations vs. manual
reconcile, and confirms the provisional callback body shape).

---

## Architecture (hexagonal / ports-and-adapters)
Domain is pure; infra plugs in via ports; channels are thin callers. (Paid off repeatedly: in-memory →
Postgres with zero domain changes; the consumer→merchant pivot reused the whole money core.)

```
services/api/src/drc_pay_api/
├── domains/                     # PURE — no HTTP/SQL/vendor knowledge
│   ├── ledger/   money.py       # Money = integer minor units (never floats)
│   │             ledger.py      # double-entry Posting/Entry (must balance)
│   ├── merchants/ models.py     # Merchant (id, name, till, settlement acct)
│   └── transactions/  state_machine.py models.py orchestrator.py ports.py pricing.py
├── application/  payments.py    # start_merchant_payment — shared by every channel
│               outcomes.py      # apply_outcome — ONE leg-resolver (webhook + sweep)
│               webhooks.py · payment_codes.py
├── adapters/  memory.py sql.py  # in-memory + SQLAlchemy/Postgres stores + ledger
├── integrations/pawapay/        # client · rail · providers · signatures · callbacks · status · simulator
├── ussd/  session.py            # USSD channel: full-text parse + QR/dial fast-path
├── jobs/reconciliation/sweep.py # D.2 — poll status endpoints → apply_outcome
├── http/   routes.py schemas.py container.py   (container.py = composition root)
│           merchant_routes.py ussd_routes.py webhook_routes.py
│           demo_routes.py      # /demo/reconcile  — off-real-money-path only (404 in prod)
│           public_routes.py    # /public/merchant, /pay — public customer endpoints (404 in prod)
├── main.py · config.py
tooling/  merchant-console/   # gated web cockpit (merchant side)
          customer-app/       # public scan-to-pay + USSD dial simulator (customer side)
          pawapay-sim/        # placeholder (use the in-process simulator)
Dockerfile · render.yaml · docs/deploy-{railway,render}.md     # deploy
```

**Layering:** dependencies point inward; `domains/` + `application/` never import a channel.

---

## How the money works (verified by tests)
Customer pays the sticker `amount`; merchant **absorbs the fee**, nets `amount − fee`; we keep `fee`
(booked to revenue only on a successful settlement). Any post-collection failure **refunds the
customer the full amount**; a failed refund → `manual_review`. Money is **integer minor units**; the
double-entry ledger is the source of truth (every posting must balance).

⚠️ **Pricing unresolved — the 1% MDR is a placeholder BELOW cost.** pawaPay round-trip ≈ 3.5–5%, so the
real MDR must be ≈5–7%+. Decision pending (ADR 0005; research `fees-and-costs.md`).

## pawaPay — the integration (sandbox-verified 2026-06-13)
- **Async:** `POST /v2/{deposits,payouts,refunds}` return ACCEPTED/REJECTED; the final outcome arrives
  via a **signed callback (RFC-9421)** or by polling `GET /v2/{deposits,payouts,refunds}/{id}` →
  `{"data":{…,"status":…},"status":"FOUND"}` (shape **confirmed**; `client._status` parses it). Push
  (D.1 webhook) and poll (D.2 sweep) both resolve a leg through one `apply_outcome` (state-guarded,
  idempotent). The simulator now mirrors this (issues op-ids, implements `StatusPoller`).
- **DRC providers:** `VODACOM_MPESA_COD`, `AIRTEL_COD`, `ORANGE_COD`. USD = 2 decimals everywhere;
  **Vodacom CDF = NONE decimals** (`providers.format_amount`). No Afrimoney.
- **Sandbox test numbers** (success ends `789`): Vodacom `243813456789`, Airtel `243973456789`, Orange
  `243893456789`; failures by suffix (deposit `…049` insufficient, etc.; payout `…089/119`). The demo
  merchants settle to the Airtel/Orange success numbers. (docs.pawapay.io/v2/docs/test_numbers)
- `predict-provider` maps a phone → operator (allow override). `active-conf` carries live limits (USD
  min Vodacom 0.5 / Airtel 0.1 / Orange 0.01, max 2500) — replace the static `_DECIMALS` map with it.

## Deploy (built; `docs/deploy-railway.md`)
- **One container** (`Dockerfile`): installs the API, runs `alembic upgrade head` then uvicorn
  (`--proxy-headers`), serving the API + the gated console (`/console`) + the public customer app
  (`/customer`). `DRCPAY_BASIC_AUTH_PASSWORD` gates everything except the customer paths, the webhook,
  and `/health`. `adapters.sql.normalize_db_url` makes a managed `postgres://` URL work for both the
  app engine and the migrations.
- **Railway** is the pick (cheap, simple; the Docker image is portable). **AWS is the eventual
  *production* target** (`infra/` Terraform, `af-south-1`, Secrets Manager — per `CLAUDE.md`).

---

## Open items / TODOs (still relevant)
- **pawaPay callback BODY shape** is still provisional — we proved the loop by *polling*, not
  callbacks. Wiring callbacks (needs the Railway public URL) confirms it; `callbacks.py` is the one
  place to adjust. Signature `@authority` = the `Host` header (proxy headers handle this behind Railway).
- **Real USSD aggregator** — rent Africa's Talking / Infobip (don't self-host); wire format + shortcode
  + MNO PIN. Our `/ussd` handler is provider-neutral and ready. *(Team action.)*
- **Merchant onboarding** — merchants are seeded; need create/manage + KYC (flag). No DB FK on
  `merchant_id` yet; Postgres `merchants` start empty.
- **Reconciliation scheduling** — the sweep works but isn't on a timer/authenticated trigger (ops
  task); no age/grace filter (would need a per-tx timestamp on the domain `Transaction`).
- **Pricing** (above) · **merchant auth** (`domains/auth/` empty) · **native mobile app** (deferred,
  web-first for now) · **Legal/licensing (BCC)** — standing flag.

---

## How to run
```bash
cd services/api && source .venv/bin/activate
ruff check . && mypy src && pytest                          # all green (118)
uvicorn --app-dir src drc_pay_api.main:app --reload         # IMPORTANT: --app-dir src

# serve the web apps from the API (set the static dirs), then open the URLs:
export DRCPAY_CONSOLE_DIR="$PWD/../../tooling/merchant-console"
export DRCPAY_CUSTOMER_DIR="$PWD/../../tooling/customer-app"
uvicorn --app-dir src drc_pay_api.main:app
#   merchant console: http://localhost:8000/console/
#   customer pay:     http://localhost:8000/customer/?m=m_alpha   (the merchant QR opens this)

# live sandbox rail: put the token in services/api/.env (DRCPAY_PAWAPAY_BASE_URL + _API_TOKEN); the
#   app auto-switches off the simulator. scripts/pawapay_smoke.py is a read-only connectivity check.
# Postgres: docker compose up -d ; export DRCPAY_DATABASE_URL=… ; alembic upgrade head
```
**Gotcha:** always run uvicorn with `--app-dir src` (the repo path has a space, which breaks pip's
editable install; tests dodge it via `pythonpath=src`).

## Git & conventions
Repo **github.com/TristanDS95/drc-pay** (`main`); **the human pushes**; commits use **no** Claude
co-author trailer. Standards in `CLAUDE.md`; ADRs in `docs/adr/` (0004 merchant-acquiring, 0005
merchant-absorbs-MDR, 0006 USSD/QR channel). Simplicity discipline: `docs/simplicity-review.md`.

## Carry-forward insights
1. **The money core is role-agnostic** — the consumer→merchant pivot reused ledger/state-machine/
   orchestrator wholesale; only vocabulary, fee placement, and a Merchant entity changed.
2. **Every channel is a thin caller** into `start_merchant_payment` — money logic written once.
3. **pawaPay is async** — push (callback, D.1) and poll (sweep, D.2) both resolve via one `apply_outcome`.
4. **Tests catch real bugs** — ledger + state machine carry the highest coverage; offline + deterministic.
5. **Invest in the money core, keep the rest minimal** — flag honest gaps rather than gold-plate.
```
