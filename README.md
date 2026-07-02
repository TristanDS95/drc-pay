# drc-pay

The DRC cross-network mobile-money payment app — **application code**.

A **merchant-facing** app for the DRC: merchants accept mobile-money payments from customers on
**any** network (Vodacom M-Pesa, Airtel, Orange), bridged behind the scenes, on rented rails
(**pawaPay**) as a **pure pass-through** (we never hold funds). The customer pays the sticker price and
the **merchant absorbs our fee (MDR)**; settlement to the merchant follows automatically, with an
automatic refund if it can't complete. 

**Customers need no app or internet** — they scan the merchant's QR or dial a USSD till. A consumer-facing
app may follow later.

> Research, product spec, and decision reports live in the sibling
> [`../drc-mvp-research/`](../drc-mvp-research/). Start there for the "why's"; this repo is "how"

## Status

**🟢 Live, end-to-end, on real pawaPay _sandbox_ rails.** Deployed on Railway as a single container
(API + both web apps + Postgres). A real phone scans a merchant's QR → pays → the payment **confirms in
real time** on both the payer's screen and the Merchant Console, driven by pawaPay's **signed callbacks**
(RFC-9421). Backend is green: ruff + `mypy --strict` clean, full pytest suite passing (plus
opt-in live-sandbox e2e tests, off by default - see [DEVLOG](docs/DEVLOG.md#how-to-run)).

- **Backend** (`backend/`, **Python / FastAPI**): payment spine (collect → settle → auto-refund),
  double-entry ledger, explicit state machine, idempotency, Merchant + Charge domains, MDR pricing,
  Postgres + Alembic, the pawaPay client/rail, signed-callback receiver, reconciliation sweep, the USSD
  channel, and **on-net same-network handling** — *facilitate & record*
  ([ADR 0009](docs/adr/0009-on-net-facilitate-and-record.md)): same-network payments are paid
  merchant-direct on the operator's own rail (non-custodial), and we record/confirm them.
- **Web UIs** (`frontend/`): the gated **Merchant Console** and the public **Customer** scan-to-pay page.
- **Not started:** the native mobile app (React Native/Expo — deliberately web-first for now; plan in
  [`docs/future-dev.md`](docs/future-dev.md)) and merchant onboarding/KYC.


## Live demo (sandbox)

- **URL:** `https://drc-pay-sandbox-production.up.railway.app`
- **Merchant Console:** open the URL → log in (user `drcpay` + the shared demo password).
- **Customer pay page:** the Console's "Charge by QR" makes a charge whose QR opens
  `…/customer/?charge=<id>` (no login) — scan, pick a network, pay.
- It runs on pawaPay's **sandbox** (test money only).

## Layout

```
drc-pay/
├── backend/           # Python / FastAPI — the money core + every channel (HTTP, USSD, webhooks)
├── frontend/
│   ├── merchant-console/  # gated web cockpit (merchant side) — Charge-by-QR, live feed, ledger
│   └── customer-app/      # public scan-to-pay (charge-driven) + USSD dial simulator (customer side)
├── docs/              # DEVLOG, future-dev, design tokens, ADRs
├── Dockerfile         # single-container image: API + both web apps, served same-origin
├── docker-compose.yml # local Postgres
└── .github/workflows/ # CI (lint, type, test)
```

Inside the backend (`backend/src/drc_pay_api/`) the design is hexagonal — the domain is pure,
infrastructure plugs in via ports, every channel is a thin caller into the same core. The **dual-rail
routing** added with on-net lives here:

```
domains/              # PURE money logic — no HTTP / SQL / vendor knowledge
  ledger/             #   Money (integer minor units) + the double-entry ledger
  merchants/ charges/ #   the payee + the scan-to-pay checkout
  transactions/       #   state machine · models · pricing · ports, and the TWO orchestrators:
                      #     orchestrator.py — cross-network: pawaPay collect → settle → auto-refund
                      #     on_net.py       — same-network: facilitate & record (no money movement)
application/          # payments.py — the single entry every channel calls; routing.py decides on-net
                      #   vs routed; outcomes.py / webhooks.py resolve async outcomes (callback + sweep)
adapters/             # in-memory + SQLAlchemy/Postgres stores (same ports)
integrations/
  pawapay/            #   rented-rails client · rail · simulator · RFC-9421 signed-callback verify
container.py          # the composition root — every channel wires through it
http/                 # FastAPI routes; the signed pawaPay callback receiver at /webhooks/pawapay
ussd/                 # feature-phone channel — a thin caller into the same core
jobs/                 # the reconciliation sweep (missed-callback safety net)
```

## Quickstart

Day-to-day we run against the **hosted sandbox**, not a local server — see
[Live demo](#live-demo-sandbox) above for the URL and logins. It's a single container (API + Merchant
Console + Customer page, same-origin) deployed on **Railway**, backed by managed Postgres, talking to
pawaPay's **sandbox** rails (test money only). Real **signed callbacks** (RFC-9421) confirm payments in
real time; the reconciliation sweep is the backstop.

- **Deploy / redeploy:** push-to-deploy from GitHub; env vars (the Postgres reference, the pawaPay
  token, the shared `DRCPAY_BASIC_AUTH_PASSWORD`) are set in Railway's dashboard. Deploy
  specifics live in [`docs/DEVLOG.md`](./docs/DEVLOG.md).
- **Secrets stay out of the repo:** the pawaPay token and the demo password live only in Railway's
  dashboard, never in git or chat.
- **Production** will move to AWS (`af-south-1`); the same Docker image is portable. (Infra notes: [`docs/future-dev.md`](docs/future-dev.md).)

### Run locally (contributors)

Still fully supported for development. With **no credentials** set it runs entirely offline — the
in-process pawaPay simulator, with seeded demo merchants — so you never touch real (or sandbox)
money (same-network payments route on-net and are recorded, no rail involved):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install ".[dev]"                                  # runtime + dev deps (ruff, mypy, pytest)
ruff check . && mypy src && pytest                    # all green (offline; sandbox tests skip)

export DRCPAY_CONSOLE_DIR="$PWD/../frontend/merchant-console"
export DRCPAY_CUSTOMER_DIR="$PWD/../frontend/customer-app"
uvicorn --app-dir src drc_pay_api.main:app --reload
#   API docs:  http://localhost:8000/docs
#   console:   http://localhost:8000/console/   (post a charge → scan/open its QR to pay)
```

Point it at the live sandbox rail instead by putting `DRCPAY_PAWAPAY_BASE_URL` +
`DRCPAY_PAWAPAY_API_TOKEN` in `backend/.env`. Postgres is optional locally
(`docker compose up -d`, then set `DRCPAY_DATABASE_URL`); without it the app uses an in-memory store.

> **Always run uvicorn with `--app-dir src`** — the repo path contains a space, which breaks pip's
> *editable* install, so we run from `src` (tests do the same via `pythonpath=src`).

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

Significant decisions are recorded as ADRs (architectural decision record) in [`docs/adr/`](./docs/adr/). 
The plain-language architecture guide is [`docs/architecture-guide.md`](./docs/architecture-guide.md)
(the Word version, `docs/DRC-Pay-Architecture-Guide.docx`, is generated from it).
