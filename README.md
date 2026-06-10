# drc-pay

The DRC cross-network mobile-money payment app — **application code**.

A consumer app that lets someone in the DRC pay **any** mobile-money number across
networks (Vodacom M-Pesa, Airtel, Orange), built on rented rails (**pawaPay**) as a
**pass-through** (we never hold funds). Smartphone app first; a feature-phone / USSD
channel is a planned, phased addition that reuses the same backend core.

> Research, product spec, and decision reports live in the sibling
> [`../drc-mvp-research/`](../drc-mvp-research/). Start there for the **why**; this
> repo is the **how**.

## Status

**Scaffold.** Structure, engineering standards, CI, and the money-correctness core
(double-entry ledger + transaction state machine, with tests) are in place. Backend
is **Python / FastAPI**; the mobile app is **React Native / Expo** (to be initialized).

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
│   └── pawapay-sim/   # local fake of pawaPay for offline dev + tests
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
