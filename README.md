# drc-pay

The DRC cross-network mobile-money payment app — **application code**.

A **merchant-facing** app for the DRC: merchants accept mobile-money payments from customers on
**any** network (Vodacom M-Pesa, Airtel, Orange), bridged behind the scenes, on rented rails
(**pawaPay**) as a **pure pass-through** (we never hold funds). The customer pays the sticker price and
the **merchant absorbs our fee (MDR)**; settlement to the merchant follows automatically, with an
automatic refund if it can't complete. **Customers need no app or internet** — they scan the merchant's
QR or dial a USSD till — so **USSD is a first-class MVP channel, not a later phase**. A consumer-facing
app may follow later.

> Research, product spec, and decision reports live in the sibling
> [`../drc-mvp-research/`](../drc-mvp-research/). Start there for the **why**; this repo is the **how**.

## Status

**🟢 Live, end-to-end, on real pawaPay _sandbox_ rails.** Deployed on Railway as a single container
(API + both web apps + Postgres). A real phone scans a merchant's QR → pays → the payment **confirms in
real time** on both the payer's screen and the Merchant Console, driven by pawaPay's **signed callbacks**
(RFC-9421). Backend is green: ruff + `mypy --strict` clean, **130 tests**.

- **Backend** (`services/api`, **Python / FastAPI**): payment spine (collect → settle → auto-refund),
  double-entry ledger, explicit state machine, idempotency, Merchant domain, MDR pricing, Postgres +
  Alembic, the pawaPay client/rail, signed-callback receiver, reconciliation sweep, and the USSD channel.
- **Web UIs** (`tooling/`): the gated **Merchant Console** and the public **Customer** scan-to-pay page.
- **Not started:** the native mobile app (`apps/mobile`, React Native/Expo — deliberately web-first for
  now) and merchant onboarding/KYC.

See [`docs/DEVLOG.md`](./docs/DEVLOG.md) for the current state and what's next, and
[`docs/DRC-Pay-Architecture-Guide.docx`](./docs/DRC-Pay-Architecture-Guide.docx) for a plain-language
tour of the whole system.

## Live demo (sandbox)

- **URL:** `https://drc-pay-sandbox-production.up.railway.app`
- **Merchant Console:** open the URL → log in (user `drcpay` + the shared demo password).
- **Customer pay page:** `…/customer/?m=m_alpha` (what the merchant's QR opens — no login).
- It runs on pawaPay's **sandbox** (test money only).

## Layout

```
drc-pay/
├── services/
│   ├── api/           # backend — FastAPI; the money logic + all channels (incl. the webhook receiver)
│   └── webhooks/      # placeholder (the receiver currently lives in services/api)
├── tooling/
│   ├── merchant-console/  # gated web cockpit (merchant side) — take payments, live feed, reconcile
│   ├── customer-app/      # public scan-to-pay + USSD dial simulator (customer side)
│   └── pawapay-sim/       # placeholder (use the in-process simulator in services/api)
├── apps/
│   ├── mobile/        # React Native + Expo — scaffolding only (not started)
│   └── admin/         # internal ops dashboard — placeholder (later)
├── infra/             # Terraform — AWS Cape Town (af-south-1), the eventual production home
├── docs/              # DEVLOG, architecture guide, deploy runbooks, ADRs
├── Dockerfile         # single-container image: API + both web apps, served same-origin
└── .github/workflows/ # CI (lint, type, test)
```

## Quickstart (backend)

```bash
cd services/api
python3 -m venv .venv && source .venv/bin/activate
pip install ".[dev]"                                  # runtime + dev deps (ruff, mypy, pytest)
ruff check . && mypy src && pytest                    # all green (130)

# Run the API + both web apps locally (point it at the static dirs, then open the URLs):
export DRCPAY_CONSOLE_DIR="$PWD/../../tooling/merchant-console"
export DRCPAY_CUSTOMER_DIR="$PWD/../../tooling/customer-app"
uvicorn --app-dir src drc_pay_api.main:app --reload
#   API docs:  http://localhost:8000/docs
#   console:   http://localhost:8000/console/
#   customer:  http://localhost:8000/customer/?m=m_alpha
```

With no credentials set it runs fully offline on an **in-process pawaPay simulator** with seeded demo
merchants — zero setup. Point it at the live sandbox by putting `DRCPAY_PAWAPAY_BASE_URL` +
`DRCPAY_PAWAPAY_API_TOKEN` in `services/api/.env`. Postgres is optional locally (`docker compose up -d`
then set `DRCPAY_DATABASE_URL`); without it the app uses an in-memory store.

**Gotcha:** always run uvicorn with `--app-dir src` — the repo path contains a space, which breaks pip's
*editable* install, so we run from `src` instead (tests do the same via `pythonpath=src`).

The whole thing also runs as one Docker image; see [`docs/deploy-railway.md`](./docs/deploy-railway.md).

## Engineering standards

These are non-negotiable because bugs here move real money:

- **Money is integer minor units, never floats** — exact arithmetic; parsed via `Decimal`.
- **The double-entry ledger is the source of truth** (not the transaction row); every posting must
  balance or it's rejected.
- **Idempotency on every money-moving request** — a retry never double-charges.
- **An explicit transaction state machine** — illegal transitions raise; they're bugs, not edge cases.
- **Reconciliation is the safety net** — assume callbacks get missed; a sweep heals stuck payments.
- **pawaPay webhooks are verified** with RFC-9421 public-key signatures (ECDSA-P256) — reject unsigned.
- **No secrets in the repo** — config via environment variables; `.env` is git-ignored.
- **ruff + `mypy --strict` + pytest** must all pass; the ledger and state machine carry the most tests.

Significant decisions are recorded as ADRs in [`docs/adr/`](./docs/adr/). The full local engineering
standards live in `CLAUDE.md` (kept on the developer's machine, not committed); the plain-language
architecture guide is [`docs/DRC-Pay-Architecture-Guide.docx`](./docs/DRC-Pay-Architecture-Guide.docx).
