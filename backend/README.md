# backend

The backend - **Python / FastAPI**. This is where the money logic lives.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # editable - site-packages points at src, so it never goes stale
```

## Run

```bash
# --app-dir src puts the package on the import path and runs straight from source, so edits take
# effect without reinstalling. Install with `pip install -e ".[dev]"`: a plain install copies src
# into site-packages and that copy goes stale, so a bare `import drc_pay_api` would run old code.
uvicorn --app-dir src drc_pay_api.main:app --reload
```

Then open **http://127.0.0.1:8000/docs** - FastAPI's auto-generated interactive page -
and try `POST /transactions`, e.g.:

```json
{"customer_msisdn": "243813456789", "merchant_id": "m_alpha", "amount": "10.00", "scenario": "success"}
```

`scenario` can be `success`, `payout_fail`, `collection_fail`, or `refund_fail` - it plays out a
simulated outcome on the in-process rail (and is ignored on the live pawaPay rail). The response
shows the final state, the full state history, and the ledger entries.

## Database

By default the API uses an in-memory store (zero setup - perfect for the demo). To run
against **Postgres**, start one with Docker (from the repo root) and point the API at it:

```bash
docker compose up -d        # starts Postgres on localhost:5432 (see ../docker-compose.yml)
export DRCPAY_DATABASE_URL=postgresql+psycopg://drcpay:drcpay@localhost:5432/drcpay
alembic upgrade head        # create/update the schema (Alembic migrations)
uvicorn --app-dir src drc_pay_api.main:app --reload
```

Unset `DRCPAY_DATABASE_URL` to switch back to the in-memory store.

### Migrations (Alembic)

The schema is managed by **Alembic**, not auto-created. After changing a model in
`src/drc_pay_api/adapters/sql.py`:

```bash
alembic revision --autogenerate -m "describe the change"   # generate a migration - review it!
alembic upgrade head                                       # apply it
```

Handy: `alembic current` (where the DB is) · `alembic history` · `alembic downgrade -1` (undo one).

## Checks

```bash
pytest            # tests (ledger + state machine carry the highest coverage)
ruff check .      # lint
mypy src          # types (strict)
```

## Structure

```
src/drc_pay_api/
├── main.py               # FastAPI app factory + middleware (thin HTTP layer)
├── config.py             # 12-factor settings from env
├── seed.py               # demo-merchant seeding (sandbox/local)
├── domains/              # framework-agnostic core - SOURCE OF TRUTH
│   ├── ledger/           # money.py (integer minor units) + ledger.py (double-entry)
│   ├── transactions/     # state_machine.py + orchestrator.py (the payment spine)
│   └── merchants/        # the Merchant entity
├── application/          # shared services: start_merchant_payment, apply_outcome, webhooks
├── adapters/             # in-memory + SQLAlchemy/Postgres stores
├── integrations/pawapay/ # the ONLY module that knows pawaPay's wire format
├── ussd/                 # the feature-phone (USSD) channel
├── jobs/reconciliation/  # the self-healing sweep for stuck transactions
└── http/                 # routes + middleware (gated console, public customer paths, webhook)
```

Principle: **`domains/` knows nothing about HTTP or pawaPay's wire format.** The HTTP API and
the USSD channel are both thin callers into the same domain services.
