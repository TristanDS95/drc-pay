# drc-pay

The DRC cross-network mobile-money payment app — **application code**.

A **merchant-facing** app for the DRC: merchants accept mobile-money payments from
customers on **any** network (Vodacom M-Pesa, Airtel, Orange), bridged behind the scenes,
on rented rails (**pawaPay**) as a **pure pass-through** (we never hold funds). The
customer pays the sticker price and the **merchant absorbs our fee (MDR)**; settlement to
the merchant is instant. **Customers need no app or internet** — they scan the merchant's
QR or dial a USSD till — so **USSD is a first-class MVP channel, not a later phase**. A
consumer-facing version may follow later.

> Research, product spec, and decision reports live in the sibling
> [`../drc-mvp-research/`](../drc-mvp-research/). Start there for the **why**; this
> repo is the **how**.

## Status

**Backend well underway** (`services/api`, **Python / FastAPI**): the payment spine,
merchant domain, MDR pricing, Postgres + Alembic, idempotency, the pawaPay client wired
into the orchestrator, and a USSD channel (with QR/dial-through) — ruff + mypy --strict
clean, **69 tests**. See [`docs/DEVLOG.md`](./docs/DEVLOG.md) for the live state. The
mobile app (**React Native / Expo**) and merchant onboarding are not started.

## Layout

```
drc-pay/
├── apps/
│   ├── mobile/        # React Native + Expo (smartphone app)
│   └── admin/         # internal support/ops dashboard (later)
├── services/
│   ├── api/           # backend — FastAPI (the money logic)
│   └── webhooks/      # pawaPay webhook receiver (separate deployable)
├── infra/             # Terraform — AWS Cape Town (af-south-1)
├── tooling/
│   ├── merchant-console/  # web cockpit for testing the app against the pawaPay sandbox
│   └── pawapay-sim/       # placeholder: standalone pawaPay fake (use the in-process sim for now)
├── docs/              # ported spec + architecture decision records (ADRs)
└── .github/workflows/ # CI
```

## Quickstart (backend)

```bash
cd services/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                    # runs the ledger + state-machine + API tests
uvicorn --app-dir src drc_pay_api.main:app --reload   # then open http://127.0.0.1:8000/docs
```

## Engineering standards

See [`CLAUDE.md`](./CLAUDE.md) — the non-negotiables (integer money, double-entry
ledger as source of truth, idempotency, signed webhooks, secrets hygiene, testing).
Significant decisions are recorded as ADRs in [`docs/adr/`](./docs/adr/).
