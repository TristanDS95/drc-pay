# Security roadmap - staged checklist and gates to real money

**Single source of truth for security posture and open security work.**
Assessed 2026-07-05 against the actual code (`main.py` auth gate, webhook verification, public routes) and the standing docs.
When an item lands, tick it here and note the commit; `DEVLOG.md` and `future-dev.md` point here rather than duplicating the list.

The staging principle: the current sandbox (test numbers, no real money, demo password) is **appropriately** secured for what it is.
Each gate below must be fully ticked before crossing into the stage it guards.

---

## Already in place (verified, keep true)

- [x] **TLS in transit** - Railway terminates HTTPS; platform-handled, not a standing task.
- [x] **Signed webhooks** - pawaPay callbacks verified with RFC-9421 public-key signatures (ECDSA-P256, DER + raw-64); unsigned or stale rejected; receiver idempotent (`integrations/pawapay/signatures.py`, `http/webhook_routes.py`).
- [x] **Server-authoritative money** - amount, fee, and recipient re-derived server-side at execution; the client is never trusted (`application/payments.py`, charges).
- [x] **Idempotency keys on every money-moving request**, inbound and outbound; a retry never double-charges.
- [x] **Explicit state machine** - illegal transitions raise (`domains/transactions/state_machine.py`).
- [x] **Double-entry ledger as source of truth** - every posting must balance or is rejected.
- [x] **Reconciliation sweep** as the missed-callback safety net (push + poll resolve through one `apply_outcome`).
- [x] **Fail-safe boot** - a non-local environment refuses to start without `DRCPAY_BASIC_AUTH_PASSWORD` (mirrors the DB fail-fast); demo controls (`/pay`, `/demo/reconcile`) are 404 in production.
- [x] **Secrets hygiene** - env vars only, `.env` git-ignored, secret-scan in CI, sandbox vs production credentials separated.
- [x] **Provenance on "paid"** - `merchant_attested` vs `rail_verified` recorded per transaction (ADR 0009).
- [x] **XSS discipline in the console** - server-derived strings escaped before `innerHTML`.

---

## GATE A - before the first real-money pilot

The bar: no real merchant or customer money until every box is ticked.

- [ ] **Merchant authentication** - replace the single shared Basic-auth password with per-merchant credentials (plan sketch in `future-dev.md`; `domains/auth/` when started).
- [ ] **Per-merchant authorization** - today any holder of the shared password can read and confirm ANY merchant's transactions.
      Directly fraud-relevant: on-net payments are merchant-attested, so the confirm endpoint must be scoped to the owning merchant.
- [ ] **USSD channel hardening** - `/ussd` is public and initiates real deposit pushes on a live rail.
      Authenticate the aggregator (shared secret and/or IP allowlist; the handler is provider-neutral so this lands in one place) and rate-limit the endpoint.
      Without it, anyone can spam payment prompts to arbitrary DRC numbers (harassment / social-engineering vector, even though no money moves without the payer's operator PIN).
- [ ] **Rate limiting + velocity/amount caps** - none exist anywhere today.
      Per-customer and per-merchant velocity caps are the first real fraud-detection layer; pawaPay's own per-operator amount limits (e.g. Vodacom 500 < x < 1,000,000 CDF) are not a substitute.
- [ ] **Lock CORS** - `allow_origins=["*"]` in `main.py`; restrict to known origins (the code comment already promises this).
- [ ] **Charge expiry** - charges are payable forever; a stale printed or forwarded QR should die after a TTL.
- [ ] **Audit logging on money-affecting actions** - especially `POST /transactions/{id}/confirm` (who attested, when, from where) and reconcile triggers; disputes are unanswerable without it.

## GATE B - before real customer data at scale / production proper

- [ ] **Field-level PII encryption at rest** - `customer_msisdn` / `settlement_msisdn` are plaintext today (acceptable while they are pawaPay test numbers; not after).
      Railway disk encryption is the baseline; application-level field encryption before storing real customer numbers at scale.
- [ ] **Verified log scrubbing** - the standard says never log PII/tokens; verify it holds once structured logging exists, with a test.
- [ ] **Data retention policy** - how long transaction PII lives, and the deletion path.
- [ ] **PIN handling (only if own customer auth is ever built)** - Argon2id, never recoverable, reset via OTP only.
      Today's design deliberately holds no customer credentials (USSD authorization happens on the operator's PIN prompt); keep it that way as long as possible.
- [ ] **Reconciliation bounds** - age filter + batch limit on the sweep (the unbounded `find_pending` scan is a self-inflicted DoS at scale).
- [ ] **Monitoring + alerting** - on webhook failure rates, reconciliation backlog, and `manual_review` queue depth (CloudWatch in the AWS plan).
- [ ] **Tested database backups** - the ledger being the source of truth makes losing it existential; backups must be restored-tested, not just configured.
- [ ] **Merchant onboarding + KYC** - the anti-money-laundering surface; an unvetted merchant base is the classic fraud entry point for a pass-through processor.
      Ties into the standing **BCC licensing** flag (legal/regulatory, tracked in DEVLOG open items).
- [ ] **Dependency scanning in CI** - secret-scan exists; add `pip-audit` and/or Dependabot.
- [ ] **Least-privilege IAM** - per-service on AWS (Terraform plan in `future-dev.md`); on Railway, keep dashboard/DB-credential access tight.

---

## Accepted fraud surface (conscious, not accidental)

**On-net "facilitate & record" (ADR 0009):** for same-network payments we hold no money and "paid" is merchant-attested, not rail-verified.
A lying merchant cannot steal through us (non-custodial, `fee=0`), but a customer who genuinely paid can be told "not received", and we arbitrate with no rail evidence.
Mitigations, in order: the provenance tag (done) → an explicit dispute flow (when volume justifies) → operator till notifications for auto-confirm (per-operator, in `future-dev.md`), which shrinks this surface structurally.

## Explicitly NOT now (correctly deferred)

- Application-level field encryption while the DB holds only sandbox test numbers (Gate B).
- Splitting the webhook receiver into its own service (availability/scaling case not yet real; `future-dev.md`).
- The SSO admin/ops dashboard with audit trails (`future-dev.md`).
- A standalone pawaPay HTTP simulator (the in-process one covers tests; deprioritized).

---

*Cross-references: `CLAUDE.md` (standing money/security standards) · `future-dev.md` "Security hardening" (pointer here) · `DEVLOG.md` open items (pointer here) · ADR 0003 (pass-through, no custody) · ADR 0009 (on-net facilitate & record).*
