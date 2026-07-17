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
- [x] **Idempotency keys on every money-moving request**, inbound and outbound; a retry never double-charges. Now **atomic in the application layer** - `start_merchant_payment` does a find-or-create guarded by the store's unique `idempotency_key` constraint, so even a concurrent double-submit yields one transaction (verified against real Postgres under a thread race), not a 500 or a second charge.
- [x] **Explicit state machine** - illegal transitions raise (`domains/transactions/state_machine.py`).
- [x] **Double-entry ledger as source of truth** - every posting must balance or is rejected.
- [x] **Reconciliation sweep** as the missed-callback safety net (push + poll resolve through one `apply_outcome`).
- [x] **Fail-safe boot** - `sandbox` refuses to start without `DRCPAY_BASIC_AUTH_PASSWORD`, `production` refuses to start without `DRCPAY_USSD_SHARED_SECRET`, and an **unrecognised `DRCPAY_ENVIRONMENT` fails closed** (a typo like `prod` can't silently skip the gates); demo controls (`/pay`, `/demo/reconcile`) are 404 in production.
- [x] **Secrets hygiene** - env vars only, `.env` git-ignored, secret-scan in CI, sandbox vs production credentials separated.
- [x] **Provenance on "paid"** - `merchant_attested` vs `rail_verified` recorded per transaction (ADR 0009).
- [x] **XSS discipline in the console** - server-derived strings escaped before `innerHTML`.

---

## GATE A - before the first real-money pilot

The bar: no real merchant or customer money until every box is ticked.

- [x] **Merchant authentication** - per-merchant credentials shipped (`domains/auth/`: Argon2id hashing, opaque 24h SHA-256 sessions, in-process login throttle; migration `e9b3c5d7f1a2`; `POST /auth/login|logout`, `GET /auth/me`). The shared Basic password now gates only the sandbox demo shell; production boots without it.
- [x] **Per-merchant authorization** - a `CurrentMerchant` dependency fences every merchant endpoint to the logged-in merchant: cross-merchant reads 404 (no id oracle), the on-net confirm is owner-only, and `POST /transactions`/`/charges` take the merchant from the session, never the body.
- [x] **USSD channel hardening** (ADR 0010) - `/ussd` is public and initiates real deposit pushes on a live rail.
      The aggregator now authenticates with a shared secret (`X-USSD-Secret`, constant-time; production refuses to boot without it), and the endpoint is rate-limited per customer number; the handler is provider-neutral so this lives in one place. IP allowlisting stays available as later defense-in-depth (see ADR 0010).
      Without it, anyone could spam payment prompts to arbitrary DRC numbers (harassment / social-engineering vector, even though no money moves without the payer's operator PIN).
- [ ] **Rate limiting + velocity/amount caps** - *partial:* per-surface anti-abuse limits now exist (USSD per-msisdn 15/min, the login throttle, and the USSD ≤10,000 USD fat-finger cap), but the **fraud-detection layer is still missing**: per-customer and per-merchant *velocity* caps, and money-amount caps enforced in the application layer (they live only in the USSD channel today, not on `/transactions`/`/charges`/`/pay`). pawaPay's own per-operator amount limits (e.g. Vodacom 500 < x < 1,000,000 CDF) are not a substitute. A shared, cross-channel limiter (Redis at scale) is the target.
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
