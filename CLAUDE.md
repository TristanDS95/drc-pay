# CLAUDE.md - engineering standards for drc-pay

This is **application code** for a payments product: a **merchant-facing** app for the
DRC that lets merchants accept mobile-money payments across networks (Vodacom M-Pesa,
Airtel, Orange) on rented rails (pawaPay), as a pure pass-through. Customers pay via the
merchant app or **USSD** - they need no app of their own (a consumer app may follow).
These standards are non-negotiable; they exist because bugs here move real money.
(Research-side standards live in `../drc-mvp-research/CLAUDE.md` - different repo,
different rules.)

## Money correctness
- **Money is integer minor units, never a float.** Use the `Money` type
  (`domains/ledger/money.py`). `0.1 + 0.2 != 0.3` in floats; we never risk it.
- **The double-entry ledger is the source of truth**, not the `transactions` row.
  Every posting must balance (debits == credits per currency) or it is rejected.
- **Idempotency keys on every money-moving request** - inbound (from the app) and
  outbound (to pawaPay). A retry must never double-charge.
- **The transaction state machine is explicit and enforced**
  (`domains/transactions/state_machine.py`). Illegal transitions raise - they are
  bugs, not edge cases to paper over.
- **Reconciliation is the safety net.** Assume webhooks get missed; a sweep resolves
  anything stuck against pawaPay's status API.
- **Never trust the client** for amount, fee, or recipient - the server re-derives
  them at execution time.

## Security & secrets
- **No secrets in the repo.** Config via env vars (12-factor); real secrets live in
  Railway's dashboard. `.env` is git-ignored; only `.env.example` is committed.
- **Verify pawaPay webhooks** with RFC-9421 public-key signatures (ECDSA-P256) - not
  HMAC. Reject anything unsigned or stale.
- **Never log** PII (phone numbers), tokens, or secrets; scrub structured logs.

(Pre-production / when-auth-exists hardening - PIN hashing, PII-at-rest encryption,
least-privilege IAM - lives in `docs/future-dev.md`, not here.)

## Channel-agnostic core
The money logic lives in `domains/` (plus the shared `application/` service), framework-
and channel-agnostic. Every channel is a **thin caller into the same domain services -
never a reimplementation**: the HTTP API (`http/`) and the **USSD channel** (`ussd/`, for
feature-phone customers) each collect their inputs their own way, then call
`application.start_merchant_payment`, which drives the one `Orchestrator`. Keep that
boundary clean; a new channel must not duplicate money logic.

## Testing
- The **ledger and state machine carry the highest coverage** - write tests first.
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

## Keep docs in sync (when you change X, update Y)
Each fact should have one source of truth. Where it's currently duplicated, update *every* copy
(these are the spots that have actually drifted):
- **What's live / current status** → `docs/DEVLOG.md` "TL;DR" is the source; the README "Status"
  section restates it - update both.
- **Run / dev-setup commands** → duplicated in *three* places: README "Run locally",
  `backend/README.md` "Run", and `docs/DEVLOG.md` "How to run". Change one, change all three.
- **Money / engineering rules** → `CLAUDE.md` (this file) is the source; README "Engineering
  standards" restates them - keep them aligned.

Single-source topics (update the one owner):
- **pawaPay contract** (endpoints, statuses, providers, amount limits, signatures) → `docs/DEVLOG.md`
  "pawaPay" section.
- **A significant / hard-to-reverse decision** → a new **ADR** in `docs/adr/` (don't bury it in a commit).
- **Deploy / env vars / secrets** → `backend/.env.example` + README "Quickstart" (specifics in DEVLOG "Deploy").
- **Visual language** → `docs/design-tokens.md` (single source; `design-tokens.html` renders it; mirrors
  research `ui-spec.md`). After editing the tokens, refresh the preview's embedded snapshot:
  `python3 docs/refresh-design-tokens-html.py` (the snapshot is what lets the page open by double-click;
  served over http it reads the `.md` live).
- **Roadmap** → DEVLOG "NEXT" (active) vs `docs/future-dev.md` (someday) - put it in the right one.
  When a "NEXT" item ships, move its write-up to `docs/history.md` (completed-work archive, newest
  first) and leave DEVLOG's TL;DR/NEXT lean - don't let finished narratives pile up in DEVLOG.
- **Product spec** → lives in `drc-mvp-research/05-product-spec/`; link, don't duplicate.
- **Plain-language architecture guide** → `docs/architecture-guide.md` (single source; the `.docx` is
  generated from it - `pandoc docs/architecture-guide.md -o docs/DRC-Pay-Architecture-Guide.docx` after editing).
- **Staff/admin user guide** → `docs/admin-guide.md` (single source; the `.docx` is generated from it -
  `pandoc docs/admin-guide.md -o docs/DRC-Pay-Staff-Guide.docx` after editing). It is written for a
  **non-technical operator**: plain language, no acronyms, and it documents what the Staff page can
  *and cannot* do. **Update it whenever you change the Staff Console, the approve/reject flow, staff
  account management, or the sign-in steps** - a stale operations guide gets someone locked out or
  gets the wrong merchant approved. If a change removes a limitation it lists, delete that warning
  in the same commit (that is how "rejecting is final" came out when Re-approve shipped).
  It embeds **real screenshots** from `docs/images/` - if your change alters what those screens look
  like, recapture them, or the guide shows buttons that no longer exist. Keep images sized in the
  markdown (`{width=6.3in}`); unsized 2x captures overflow the page.

Don't hard-code drift-prone values (test counts, dates) in prose - the README/DEVLOG count split came
from exactly that.
