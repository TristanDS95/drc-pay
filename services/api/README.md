# services/api

The backend — **Python / FastAPI**. This is where the money logic lives.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
# --app-dir src puts the package on the import path. (This repo sits under a path
# containing a space, which breaks pip editable installs; --app-dir sidesteps that.)
uvicorn --app-dir src drc_pay_api.main:app --reload
```

Then open **http://127.0.0.1:8000/docs** — FastAPI's auto-generated interactive page —
and try `POST /transactions`, e.g.:

```json
{"payer_msisdn": "243800000001", "payee_msisdn": "243810000002", "amount": "10.00", "scenario": "success"}
```

`scenario` can be `success`, `payout_fail`, `collection_fail`, or `refund_fail`. The
response shows the final state, the full state history, and the ledger entries.

## Database

By default the API uses an in-memory store (zero setup — perfect for the demo). To run
against **Postgres**, start one with Docker (from the repo root) and point the API at it:

```bash
docker compose up -d        # starts Postgres on localhost:5432 (see ../../docker-compose.yml)
export DRCPAY_DATABASE_URL=postgresql+psycopg://drcpay:drcpay@localhost:5432/drcpay
alembic upgrade head        # create/update the schema (Alembic migrations)
uvicorn --app-dir src drc_pay_api.main:app --reload
```

Unset `DRCPAY_DATABASE_URL` to switch back to the in-memory store.

### Migrations (Alembic)

The schema is managed by **Alembic**, not auto-created. After changing a model in
`src/drc_pay_api/adapters/sql.py`:

```bash
alembic revision --autogenerate -m "describe the change"   # generate a migration — review it!
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
├── main.py              # FastAPI app (thin HTTP layer)
├── config.py           # 12-factor settings from env
├── domains/            # the framework-agnostic core (reused by the future USSD gateway)
│   ├── ledger/         # money.py (integer minor units) + ledger.py (double-entry) — SOURCE OF TRUTH
│   ├── transactions/   # state_machine.py (the 10-state machine)
│   ├── auth/           # OTP + PIN (to build)
│   └── recipients/     # recipient lookup / Hakikisha name preview (to build)
├── integrations/
│   └── pawapay/        # the ONLY module that knows pawaPay's wire format
├── jobs/
│   └── reconciliation/ # the self-healing sweep for stuck transactions (to build)
└── http/               # routes + middleware: idempotency, rate-limit, auth (to build)
```

Principle: **`domains/` knows nothing about HTTP or pawaPay's wire format.** The HTTP
layer and the future USSD gateway are both thin callers into the same domain services.
