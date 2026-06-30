# CLAUDE.md — engineering standards for drc-pay

This is **application code** for a payments product: a **merchant-facing** app for the
DRC that lets merchants accept mobile-money payments across networks (Vodacom M-Pesa,
Airtel, Orange) on rented rails (pawaPay), as a pure pass-through. Customers pay via the
merchant app or **USSD** — they need no app of their own (a consumer app may follow).
These standards are non-negotiable; they exist because bugs here move real money.
(Research-side standards live in `../drc-mvp-research/CLAUDE.md` — different repo,
different rules.)

## Money correctness
- **Money is integer minor units, never a float.** Use the `Money` type
  (`domains/ledger/money.py`). `0.1 + 0.2 != 0.3` in floats; we never risk it.
- **The double-entry ledger is the source of truth**, not the `transactions` row.
  Every posting must balance (debits == credits per currency) or it is rejected.
- **Idempotency keys on every money-moving request** — inbound (from the app) and
  outbound (to pawaPay). A retry must never double-charge.
- **The transaction state machine is explicit and enforced**
  (`domains/transactions/state_machine.py`). Illegal transitions raise — they are
  bugs, not edge cases to paper over.
- **Reconciliation is the safety net.** Assume webhooks get missed; a sweep resolves
  anything stuck against pawaPay's status API.
- **Never trust the client** for amount, fee, or recipient — the server re-derives
  them at execution time.

## Security & secrets
- **No secrets in the repo.** Config via env vars (12-factor); real secrets live in
  Railway's dashboard. `.env` is git-ignored; only `.env.example` is committed.
- **Verify pawaPay webhooks** with RFC-9421 public-key signatures (ECDSA-P256) — not
  HMAC. Reject anything unsigned or stale.
- **PINs: Argon2id, never logged, never recoverable** (reset only via OTP).
- **Never log** PINs, full PII, tokens, or secrets. Scrub structured logs.
- **Least-privilege access to secrets and data; encrypt PII at rest; TLS everywhere.**

## Channel-agnostic core
The money logic lives in `domains/` (plus the shared `application/` service), framework-
and channel-agnostic. Every channel is a **thin caller into the same domain services —
never a reimplementation**: the HTTP API (`http/`) and the **USSD channel** (`ussd/`, for
feature-phone customers) each collect their inputs their own way, then call
`application.start_merchant_payment`, which drives the one `Orchestrator`. Keep that
boundary clean; a new channel must not duplicate money logic.

## Testing
- The **ledger and state machine carry the highest coverage** — write tests first.
- Full happy path **and** every failure branch (collection fail, payout fail →
  refund, timeout → reconciliation) run against the in-process `SimulatedPaymentRail`
  (`integrations/pawapay/simulator.py`), offline and deterministic.
- Separate **sandbox vs production** pawaPay credentials and deploy environments, always.

## Workflow & conventions
- **Python:** ruff (lint/format) + mypy (strict on `src`) + pytest; `src` layout.
- **Trunk-based**, short-lived branches, protected `main`. CI must pass: lint, type,
  test, secret-scan.
- **Conventional Commits** (`feat:`, `fix:`, `chore:` …).
- **Record significant decisions as ADRs** in `docs/adr/` (see `_template.md`).
