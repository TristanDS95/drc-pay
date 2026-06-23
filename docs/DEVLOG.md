# DRC Pay — Development Log & Handoff

**Last updated:** 2026-06-20 · **Read this first to resume work.**

**Product:** a **merchant-facing** app for the DRC: merchants accept mobile-money payments across
networks (Vodacom M-Pesa, Airtel, Orange) on **rented rails (pawaPay)** as a **pure pass-through**
(we never hold funds). Customers pay with **no app of their own** — they scan a merchant's charge QR,
or dial USSD. Research is the sibling `../drc-mvp-research/`; this repo (`drc-pay/`) is the app.

---

## TL;DR — where we are
- **🟢 LIVE on Railway, end-to-end on real pawaPay sandbox** (`https://drc-pay-sandbox-production.up.railway.app`;
  Postgres `drc-pay-db`; demo merchants auto-seeded). Real phone → scan a charge QR → pay → confirms
  **in real time** on both the payer's screen and the Merchant Console.
- **Signed callbacks (RFC-9421) wired & verifying** — deposit/payout outcomes arrive by push; the
  reconciliation sweep is the backstop. The pawaPay **v2 contract is confirmed** (see that section).
- **Scan-to-pay is a "charge" (checkout):** merchant posts an amount → a QR carries the charge id →
  the customer is charged exactly that (server-authoritative). The old static per-merchant QR is gone.
- **Real per-network-pair fees** (pawaPay published cost, **pass-through, no margin yet**) replaced the
  flat 1%; pawaPay's cost is now booked to **`expense:pawapay`** and `revenue:fees` holds only the
  **margin** (0 today) — ADR 0007. See "How the money works".
- **Backend green:** ruff + mypy --strict clean, **148 tests**. Payment spine (collect → settle →
  auto-refund), double-entry ledger, 10-state machine, idempotency, Merchant + Charge domains, Postgres
  + Alembic, pawaPay client/rail, signed-callback receiver, reconciliation sweep, USSD channel. **On-net
  = facilitate & record ([ADR 0009](adr/0009-on-net-facilitate-and-record.md)), backend DONE.**
  Same-network payments are paid **merchant-direct on the operator's own rail** (we never touch the
  money); we record an *awaiting-confirmation* txn, the merchant taps **Confirm received**, and it's
  marked paid (**merchant-attested**). The operator-API "direct-collect" approach is **retired** (it
  would make us the merchant → custody → EMI licence). The on-net **UI is now built** (customer hand-off,
  merchant Confirm-received, per-merchant till) — the slice is complete; see NEXT for the next rocks.
- **Web UIs:** **Merchant Console** (gated) — "Charge by QR", live feed, ledger drill-down, a
  de-emphasized reconcile fallback, and an **on-net "Confirm receipt"** card; **Customer page** (public) —
  scan → locked amount → pick network → pay, confirms live with the fee shown, or an **on-net hand-off**
  (pay the merchant directly on the operator — their till when set, else their number) when same-network.

## ▶ NEXT — biggest open rocks (rough priority; confirm the pick before building)

**On-net same-network — "facilitate & record" ([ADR 0009](adr/0009-on-net-facilitate-and-record.md)); backend + UI DONE.**
We do NOT route or hold money on-net: the customer pays the merchant **directly on the operator's own
rail** (their till whenever they have one, else their number), and we **record & confirm** the sale —
non-custodial, no operator money-API, `fee=0`. Cross-network stays on pawaPay. "Paid" is tagged
**merchant-attested** (on-net) vs **rail-verified** (pawaPay).
- **DONE — trim + backend flow ✅ (147 tests green).** Removed the operator-API machinery
  (`DirectCollectRail`, the `airtel`/`mpesa` scaffolds, `simulated_direct.py`, the `DRCPAY_ONNET_SIMULATE`
  toggle). `OnNetOrchestrator` is rail-free (records *awaiting confirmation* → `on_confirm` posts the one
  ledger entry, paid). `start_merchant_payment` routes same-network → on-net awaiting (all pairs, via
  `ON_NET_PROVIDERS` in `routing.py`). **`POST /transactions/{id}/confirm`** (merchant-gated;
  `?received=false` for not-received; idempotent) resolves it. A **`provenance`** field
  (`merchant_attested` | `rail_verified`) on the txn + responses, persisted via migration
  `a7c1e9f04b2d`. `/pay` exposes `on_net` + `pay_to_msisdn` + `pay_to_operator` for the hand-off.
- **DONE — the UI slice ✅.** Customer page (`frontend/customer-app`): when `on_net`, a hand-off card —
  "pay `<merchant>` directly on `<operator>`" showing the merchant's **till** when set (else their number) +
  a live waiting state that polls `/public/transaction` until paid / not-received. Merchant console
  (`frontend/merchant-console`): a **"On-net — confirm receipt"** card listing awaiting on-net payments,
  each with **Confirm received** / **Not received** → `POST /transactions/{id}/confirm`; those rows are kept
  out of the pawaPay reconcile safety-net, and the detail modal shows **assurance** (merchant-attested vs
  rail-verified). **Per-merchant operator till** added (`Merchant.operator_till`, migration `c3e8f1a9b7d2`,
  seeded on Alpha/Gamma, exposed via `/pay` `pay_to_till` + `/merchants`); `/pay` prefers it over the number.
- **To confirm with operators (not blocking the MVP):** the DRC "pay a merchant till" UX + tariff per
  operator, and whether tills emit a merchant-payment notification (the path to auto-confirm).

1. **Pricing — the decision this all serves.** The ledger now splits cost from revenue (**ADR 0007**):
   pawaPay's per-pair cost (3.5–5%) → `expense:pawapay`, and `revenue:fees` holds the **margin** — which
   is **0 today** (MDR == cost). The remaining decision is the **MDR margin/model**: set `mdr = cost +
   margin` in `pricing.py` and the surplus flows to revenue automatically (ADR 0005; research
   `fees-and-costs.md`).
2. **Merchant onboarding** — merchants are seeded (`seed.py`); need a create/manage flow + KYC (no
   onboarding UI/API; no DB FK on `merchant_id`).
3. **Real USSD aggregator** — rent Africa's Talking / Infobip; wire shortcode + MNO PIN. Our
   provider-neutral `/ussd` handler is ready. *(Also where the static-till QR returns.)*
4. **Production hardening** — AWS (Terraform, `af-south-1`, Secrets Manager — notes in `future-dev.md`); lock CORS to
   known origins; reconciliation on an authenticated schedule. Minor: charge expiry (none yet).

---

## Architecture (hexagonal / ports-and-adapters)
Domain is pure; infra plugs in via ports; channels are thin callers.

```
backend/src/drc_pay_api/
├── domains/                  # PURE — no HTTP/SQL/vendor knowledge
│   ├── ledger/   money.py    # Money = integer minor units (never floats)
│   │             ledger.py   # double-entry Posting/Entry (must balance)
│   ├── merchants/ models.py  # Merchant (id, name, till, settlement acct)
│   ├── charges/  models.py   # Charge (merchant-posted amount); status DERIVED from its payment
│   └── transactions/  state_machine.py models.py orchestrator.py ports.py
│                      pricing.py   # real per-(payer,merchant)-network-pair fee, pass-through
├── application/  payments.py # start_merchant_payment — shared by every channel; computes the fee
│               outcomes.py   # apply_outcome — ONE leg-resolver (webhook + sweep)
│               webhooks.py · payment_codes.py
├── adapters/  memory.py sql.py   # in-memory + SQLAlchemy/Postgres stores (tx, ledger, merchant, charge)
├── integrations/pawapay/    # client · rail · providers · signatures · callbacks · status · simulator
├── ussd/  session.py        # USSD channel: full-text parse + dial fast-path
├── jobs/reconciliation/sweep.py   # missed-callback safety net → apply_outcome
├── http/   routes.py schemas.py container.py (composition root)
│           merchant_routes.py charge_routes.py ussd_routes.py webhook_routes.py
│           demo_routes.py     # /demo/reconcile — off-real-money path only (404 in prod)
│           public_routes.py   # /public/{merchant,charge,transaction}, /pay — public (sandbox-gated)
├── main.py · config.py · seed.py   # seed.py = demo-merchant seeding (entrypoint, sandbox/local)
frontend/ merchant-console/   # gated cockpit: Charge-by-QR, take-payment, live feed
          customer-app/       # public scan-to-pay (charge-driven) + USSD dial sim
Dockerfile                              # deploy (single container, on Railway)
```
**Layering:** dependencies point inward; `domains/` + `application/` never import a channel.

---

## How the money works (verified by tests)
Customer pays the sticker `amount`; the merchant **absorbs the fee (MDR)** and nets `amount − fee`.
pawaPay's round-trip cost is booked to **`expense:pawapay`** (per leg, as each completes); whatever is
left of the MDR after cost — the **margin** — goes to **`revenue:fees`**. With **no margin set yet the
MDR equals cost, so revenue is exactly 0** and expense carries the whole fee (we keep nothing). A
post-collection failure **refunds the customer in full** — the sunk collection fee stays in expense, a
real loss; a failed refund → `manual_review`. Money is **integer minor units**; the double-entry ledger
is the source of truth (every posting balances). See **ADR 0007** (cost is an expense, not revenue).

**Fee = real pawaPay round-trip cost for the network pair** (`pricing.py`): collect fee on the payer's
operator + payout fee on the merchant's (Vodacom 2.5/2.0, Airtel 3.0/2.0, Orange 3.0/1.0 — collect/payout
%), i.e. 3.5–5.0% per pair. The MDR **passes that cost straight through — no margin yet**; margin is the
open pricing decision (ADR 0005; research `fees-and-costs.md`).

## Charges (checkout) — the scan-to-pay path
Merchant posts an amount → `POST /charges` → a `Charge` + a QR encoding `/customer/?charge=<id>`. The
customer who scans it pays exactly that (`POST /pay {charge_id}` — amount + merchant taken from the
charge, never the client; the txn links back; double-pay rejected). A charge's status is **derived** from
its linked transaction (no stored status to drift): awaiting → processing → paid / declined / refunded.
Console "Charge by QR" creates one and polls it live; the public `GET /public/charge/{id}` feeds the
payer page.

## pawaPay — the integration (v2, live-callback-verified)
- **Async:** `POST /v2/{deposits,payouts,refunds}` → ACCEPTED/REJECTED; final outcome via a **signed
  callback (RFC-9421)** or polling `GET /v2/.../{id}`. Push (webhook) + poll (sweep) both resolve a leg
  through one `apply_outcome` (state-guarded, idempotent).
- **Contract CONFIRMED (docs + real callbacks):** callback body is **FLAT** (top-level
  `depositId`/`payoutId`/`refundId` + `status`); the **status endpoint wraps** under
  `{"status":"FOUND","data":{…}}`. Terminal = `COMPLETED`/`FAILED`; others → PENDING (fail-safe).
  Signatures: ECDSA-P256, components `@method @authority @path signature-date content-digest content-type`,
  label `sig-pp`; pawaPay sends **DER** (~70 bytes) — `signatures.py` accepts DER + raw-64. Public key is
  **auto-fetched** from `GET /v2/public-key/http` at startup (override via `DRCPAY_PAWAPAY_PUBLIC_KEY`).
- ⚠️ **Token gotcha:** must be a **sandbox** token (matches `api.sandbox.pawapay.io`); a live token reads
  "invalid". Paste cleanly in Railway (no quotes/whitespace/`Bearer `).
- **DRC providers:** `VODACOM_MPESA_COD`, `AIRTEL_COD`, `ORANGE_COD`. USD = 2 decimals; Vodacom CDF = 0.
  **Sandbox test numbers:** operator prefix + last-3-digit outcome (`…789` success, `…049` insufficient):
  Vodacom `243813456789`, Airtel `243973456789`, Orange `243893456789` (docs.pawapay.io/v2/docs/test_numbers).
  Open: replace the static `_DECIMALS` map with live `active-conf`.

## Deploy — 🟢 LIVE on Railway
- One `Dockerfile`: install API → `alembic upgrade head` → **seed demo merchants** (`python -m
  drc_pay_api.seed`, sandbox/local only; **production starts empty**) → uvicorn (`--proxy-headers`),
  serving the API + gated `/console` + public `/customer`. `DRCPAY_BASIC_AUTH_PASSWORD` gates all but the
  customer paths, the webhook, and `/health`.
- ⚠️ **`DRCPAY_DATABASE_URL` must be a working reference** (`${{drc-pay-db.DATABASE_URL}}`, **no quotes**)
  or the app silently runs in-memory and the DB stays empty. Verify: deploy logs show migrations +
  `[seed] demo merchants ready`; the Data tab has tables.
- **On-net demo (optional):** `DRCPAY_ONNET_SIMULATE=true` makes same-network on-net routing visible on
  the sandbox — ⚠ **simulated** (fakes the operator confirmation, no real money); unset → all payments
  via pawaPay. Real operator on-net is a v2 item (see NEXT).
- **AWS is the eventual production target** (notes in `future-dev.md`); the Docker image is portable. Alembic head:
  `c3e8f1a9b7d2` (adds `merchants.operator_till`).

---

## Open items / TODOs
**Pricing margin** (above — the decision this serves) · **merchant onboarding + KYC** · **real USSD
aggregator** · **reconciliation on a schedule** (sweep exists; no timer/auth trigger; no age filter) ·
**merchant auth** (`domains/auth/` empty) · **lock CORS** before prod · **native mobile app** (deferred,
web-first) · **charge expiry** (none — charges stay payable until paid) · **refund-leg fee** (pawaPay bills refunds ≈
the disbursement rate — Plans page; our refund path books only the sunk collection fee, and whether
pawaPay reverses that collection fee is unconfirmed; research `fees-and-costs.md`) ·
**Legal/licensing (BCC)** — standing flag.

**Longer-horizon / someday** (mobile app · admin dashboard · AWS infra · splitting the webhook receiver
into its own service): see [`future-dev.md`](./future-dev.md).

## How to run
```bash
cd backend && source .venv/bin/activate
ruff check . && mypy src && pytest                          # all green (148)
export DRCPAY_CONSOLE_DIR="$PWD/../frontend/merchant-console"
export DRCPAY_CUSTOMER_DIR="$PWD/../frontend/customer-app"
uvicorn --app-dir src drc_pay_api.main:app                  # console /console/ ; pay via "Charge by QR"
# live sandbox rail: token in backend/.env (DRCPAY_PAWAPAY_BASE_URL + _API_TOKEN) → off the simulator.
# Postgres: docker compose up -d ; export DRCPAY_DATABASE_URL=… ; alembic upgrade head
```
**Gotcha:** the repo path has a space → pip *editable* installs break. Run uvicorn with `--app-dir src`;
tests use `pythonpath=src`.

## Git & conventions
Repo **github.com/TristanDS95/drc-pay** (`main`); **the human pushes**; commits use **no** Claude
co-author trailer; Conventional Commits; keep ruff + mypy + pytest green. **`CLAUDE.md` is local-only**
(gitignored, not on GitHub) — the engineering standards. Plain-language tour:
`docs/DRC-Pay-Architecture-Guide.docx`. ADRs in `docs/adr/`. Simplicity: `docs/simplicity-review.md`.

## Carry-forward insights
1. **Money core is role- and channel-agnostic** — every channel (HTTP, USSD, charge) is a thin caller
   into `start_merchant_payment`; ledger/state-machine/orchestrator are written once.
2. **pawaPay is async** — callback (push) and sweep (poll) both resolve via one `apply_outcome`.
3. **Tests catch real bugs** and stay offline/deterministic via the in-process simulator.
4. **Invest in the money core; flag honest gaps rather than gold-plate.**
```
