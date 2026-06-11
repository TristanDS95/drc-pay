# DRC Pay — Development Log & Handoff

**Last updated:** 2026-06-11 · **Read this first to resume work.**

This is the running state of the build. The product: a DRC consumer app to **pay any
mobile-money number across networks** (Vodacom M-Pesa, Airtel, Orange) on **rented rails
(pawaPay)** as a **pure pass-through** (we never hold funds). Research lives in the
sibling `../drc-mvp-research/`; this repo (`drc-pay/`) is the app.

---

## TL;DR — where we are
- **Backend (`services/api`)** is well underway and fully green: ruff + mypy --strict
  clean, **40 tests passing**. Built: the payment spine, Postgres persistence, Alembic
  migrations, idempotency, and the pawaPay outbound client (Phases A+B).
- **Mobile app (`apps/mobile`)**: not started (only `theme/tokens.ts`). A **web
  phone-mock** (`tooling/phone-mock`) exists for visual testing (bilingual + ops console).
- **Immediate next:** wire pawaPay into the orchestrator (**Phase C**, fully specced
  below), then the callback receiver (**Phase D**), then live sandbox test (**Phase E**,
  needs credentials).

---

## Architecture (hexagonal / ports-and-adapters)
The domain is pure; infrastructure plugs in via ports. This has repeatedly paid off
(we swapped in-memory → Postgres with **zero** domain changes).

```
services/api/src/drc_pay_api/
├── domains/                     # PURE — no HTTP/SQL/vendor knowledge
│   ├── ledger/  money.py        # Money = integer minor units (never floats)
│   │            ledger.py       # double-entry Posting/Entry (must balance)
│   └── transactions/
│        state_machine.py        # 10-state machine; illegal transitions raise
│        models.py               # Transaction (id, payer/payee, amount, fee, state,
│                                #   history, idempotency_key)
│        orchestrator.py         # THE SPINE: collect→payout→refund; emits a trace
│        ports.py                # PaymentRail, TransactionStore, LedgerPort, Recorder
│        pricing.py              # default_fee = 1% (placeholder)
├── adapters/
│   ├── memory.py                # in-memory store/ledger/recorder (demo + tests)
│   └── sql.py                   # SQLAlchemy 2.0 Postgres store + ledger
├── integrations/pawapay/
│   ├── client.py                # PawaPayClient (deposits/payouts/refunds/predict)
│   ├── providers.py             # DRC codes + provider_decimals/format_amount
│   └── simulator.py             # SimulatedPaymentRail (the demo rail)
├── http/  routes.py schemas.py container.py   # thin API layer + composition root
├── jobs/reconciliation/         # EMPTY — planned (poll for stuck/missed callbacks)
├── main.py                      # create_app() factory; module-level `app`
└── config.py                    # 12-factor settings (DRCPAY_* env vars)
migrations/                      # Alembic (baseline + idempotency)
tests/                           # 40 tests
```

**Layering rule:** dependencies point inward. `domains/` never imports adapters/http.

---

## Built & verified (ruff + mypy --strict clean, 40 tests)
- **Payment spine** (`orchestrator.py`): collect → payout → payee+fee→revenue; on payout
  failure → auto-refund payer the **full amount+fee**; collection failure moves nothing;
  failed refund → `manual_review`. Every step enforced by the state machine and recorded
  as a balanced ledger posting.
- **HTTP API**: `POST /transactions` (with a demo `scenario` + `Idempotency-Key` header),
  `GET /transactions/{id}`, `GET /transactions`, `GET /health`, `/docs`. Response
  includes a human-readable **operations trace**.
- **Postgres persistence** (`sql.py`): `transactions` + append-only `ledger_entries`;
  switchable via `DRCPAY_DATABASE_URL` (set → Postgres, blank → in-memory).
- **Alembic migrations**: baseline (`d11f02bd69d8`) + idempotency key (`b79d18ed3797`).
- **Idempotency**: `Idempotency-Key` header + unique DB constraint; a repeat key returns
  the original transaction (no double-charge).
- **pawaPay client** (`client.py`): deposits/payouts/refunds + `predict_provider` +
  provider-aware amount decimals; tested against a mocked httpx transport.
- **Web phone-mock** (`tooling/phone-mock`): EN/FR, send flow, live ops console.

---

## Money & fee behavior (confirmed correct)
- Fee = **1% placeholder** (`pricing.py`).
- On **any** failure/incomplete transfer, the payer is refunded the **full charge
  (amount + fee)**; the fee is booked to revenue **only** on a successful payout.
  (Verified in the Postgres e2e: payout_fail → payer net-zero, no `revenue:fees` row.)
- *Cost note (later):* a failed payout still incurred pawaPay's collection cost — we'd
  absorb that as cost-of-goods (P&L), not pass it to the customer.

---

## pawaPay — verified API contract (research 2026-06-11)
Full findings: `../drc-mvp-research/02-findings/aggregators/pawapay-api-deep-dive.md`
and `.../cross-cutting/operator-detection.md`.

- **Base:** `https://api.sandbox.pawapay.io` / `https://api.pawapay.io`. **Auth:**
  `Authorization: Bearer <token>` (sandbox/prod tokens from the dashboard).
- **Financial:** `POST /v2/deposits` (collect), `POST /v2/payouts` (pay),
  `POST /v2/refunds` (needs the original `depositId`). Each: UUIDv4 op-id + payer/recipient
  `{phoneNumber, provider}` + amount(string) + currency. Idempotent on the op-id.
- **Operator detection:** `POST /v2/predict-provider` `{phoneNumber}` → `{country,
  provider, phoneNumber(sanitised)}`. High accuracy, **not 100% → allow override.**
  (We do NOT build our own detector.)
- **Dynamic config:** `GET /v2/active-conf` → per-provider status, currencies,
  `decimalsInAmount`, min/max amounts. (Replace our static decimals map with this later.)
- **ASYNC:** financial POSTs return `ACCEPTED/REJECTED/DUPLICATE_IGNORED`; the **final
  outcome arrives via a signed callback (RFC-9421)** → **a callback receiver is
  mandatory** (Phase D).
- **DRC providers:** `VODACOM_MPESA_COD`, `AIRTEL_COD`, `ORANGE_COD`. ⚠️ **Vodacom
  M-Pesa CDF takes NO decimals** (handled in `providers.format_amount`). No Afrimoney.

---

## pawaPay integration roadmap
- **A — outbound client** ✅ committed (`37b208b`).
- **B — predict-provider + decimals** ✅ committed (`1d86a64`).
- **C — wire into the orchestrator (NEXT).** Concretely:
  1. `ports.PaymentRail`: add `provider: str` to `request_collection`/`request_payout`
     (and a provider for refund amount formatting). Update `SimulatedPaymentRail`,
     `FakePaymentRail`, and the orchestrator calls accordingly.
  2. New `integrations/pawapay/rail.py`: `PawaPayRail` implementing `PaymentRail` by
     wrapping `PawaPayClient` (generate UUIDv4 op-ids; translate Money/provider).
  3. **Persist pawaPay op-ids**: add `deposit_id`/`payout_id`/`refund_id` columns to
     `transactions` (+ Alembic migration) so callbacks correlate back and refunds can
     reference the original `depositId`. Also store the resolved `provider`.
  4. **Route**: call `predict_provider` to resolve the recipient's operator (with an
     override path); pass `provider` through `start_transaction`.
  5. **container.build_container**: select `PawaPayRail` when `DRCPAY_PAWAPAY_*` is set,
     else `SimulatedPaymentRail`.
- **D — callback/webhook receiver**: endpoint (or `services/webhooks`) that verifies the
  RFC-9421 signature, looks up the transaction by pawaPay op-id, and calls the
  orchestrator's `on_*_result`. Plus a reconciliation job polling status for missed
  callbacks (`jobs/reconciliation`).
- **E — live sandbox test**: **TEAM ACTION** — sign up at
  `dashboard.sandbox.pawapay.io`, set `DRCPAY_PAWAPAY_BASE_URL` +
  `DRCPAY_PAWAPAY_API_TOKEN`, then exercise the real flow. (We don't sign up.)

---

## Open items / TODOs (not blocking, but known)
- Idempotency: graceful **concurrent-race** handling (catch unique violation → return
  existing) — currently only sequential retries are graceful.
- Ledger **append-only** is by convention; enforce at DB level later.
- Alembic auto-names constraints; add a naming convention for deterministic names.
- Replace the static `_DECIMALS` map with live `active-conf`.
- Not started: **auth** (phone+OTP+PIN), **recipients/Hakikisha**, the **mobile app**.
- **Legal/licensing (BCC)** — standing flag, not yet investigated.

---

## How to run
```bash
# from services/api, with the venv active
cd services/api && source .venv/bin/activate

# checks
ruff check . && mypy src && pytest

# API (in-memory; zero setup)
uvicorn --app-dir src drc_pay_api.main:app --reload        # IMPORTANT: --app-dir src

# API on Postgres
docker compose up -d                                        # from repo root
export DRCPAY_DATABASE_URL=postgresql+psycopg://drcpay:drcpay@localhost:5432/drcpay
alembic upgrade head                                        # apply migrations
uvicorn --app-dir src drc_pay_api.main:app --reload

# web phone-mock (second terminal)
python3 -m http.server 5500 --directory "<repo>/tooling/phone-mock"   # open localhost:5500

# view the DB: TablePlus → host 127.0.0.1, port 5432, user/pass/db = drcpay
```
**Gotcha:** always run uvicorn with `--app-dir src` — this repo sits under a path with a
space, which breaks pip's editable install (tests dodge it via `pythonpath=src`).

---

## Git
- Repo: **github.com/TristanDS95/drc-pay** (public), branch `main`. Local is a few commits
  ahead of origin at times — the human pushes (`git push`); commits use **no** Claude
  co-author trailer.
- Research workspace `../drc-mvp-research/` is **separate** (not in this git repo).

---

## Latest insights (carry forward)
1. **pawaPay solves operator detection** (`predict-provider`) — don't build our own.
2. **pawaPay is asynchronous** — the callback receiver (Phase D) is mandatory, not optional.
3. **Vodacom M-Pesa CDF = no decimals** — amount formatting must be provider-aware.
4. **Hexagonal architecture keeps paying off** — adapters swap with no domain change.
5. **Tests catch real bugs** (e.g. the idempotency wire-through) — keep writing them first.
6. The skeptic's check we keep applying: invest quality in the **money core**, keep
   everything else minimal; flag honest gaps rather than gold-plate.
