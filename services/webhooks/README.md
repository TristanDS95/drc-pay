# services/webhooks

The pawaPay **webhook receiver**, deliberately separate from `services/api`.

**Why separate:** it's a public endpoint whose security model is **signature
verification** (RFC-9421 public-key, ECDSA-P256 — *not* HMAC), and it must stay
available so we never lose payment-outcome events. That's a different scaling and
hardening profile from the user-facing, JWT-authenticated API — so it's its own
deployable.

**Responsibilities (to build):**
- Verify pawaPay's signature on every inbound event; reject unsigned or stale ones.
- Translate the event into a domain action (advance the transaction state machine via
  `services/api`'s domain layer).
- Be **idempotent** — the same event may arrive more than once.
- **Dead-letter** anything it can't process, for the reconciliation job to resolve.
