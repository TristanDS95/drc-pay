# services/api

The backend — **Python / FastAPI**. This is where the money logic lives.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
uvicorn drc_pay_api.main:app --reload     # http://127.0.0.1:8000/health
```

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
