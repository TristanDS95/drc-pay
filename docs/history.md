# DRC Pay - completed work history

Finished milestones, moved out of [`DEVLOG.md`](./DEVLOG.md) to keep it focused on current state and
open work. Newest first. For where things stand now and what is next, read DEVLOG.md; this file is the
archive of how we got here.

---

## 2026-07-18 - Merchant console: mobile-first + simple/dev views
The console is now mobile-first (one-column phone layout, 48px touch targets, the charge → QR →
confirm-receipt flow up top; desktop: merchant tile on top, Charge-by-QR | feature-phone side by side,
payment history below) and ships **two views**: the plain **simple view** every merchant sees (hero,
Charge by QR, USSD sticker, on-net confirm, pending count, feed) and a **dev view** (ops trace,
take-payment + USSD dial simulators, force-reconcile, technical txn detail: pawaPay op ids / state
history / ledger) behind a **DEV toggle**. Gating is CSS-only (`[data-dev]` / `[data-simple]` on one
shared page - no duplicated markup to drift) and the toggle renders only where `/demo/*` exists
(local/sandbox), so production merchants can never reach the diagnostic view.

## 2026-07-16 - Post-USSD hardening & review pass
A max-effort review of the USSD channel surfaced 17 findings; the money- and security-critical ones
were fixed and adversarially re-verified. Highlights: **idempotency is now atomic in the application
layer** - `start_merchant_payment` owns a find-or-create backed by the store's unique `idempotency_key`
constraint (a concurrent double-submit yields exactly one transaction, never a double charge or a 500;
verified with a 12-thread race against real Postgres). **Strict typed-amount parsing**
(`Money.from_user_input` rejects thousands-grouped / scientific-notation / Unicode-digit input instead
of silently misreading it). **msisdn hardening** (`fullmatch` + ASCII digits; `+`/no-`+` normalised to
one identity for the rate-limit bucket and the idempotency key). **Fail-closed boot** on an unrecognised
`DRCPAY_ENVIRONMENT` (a typo like `prod` no longer skips the safety gates). Plus dead-code prune,
`ruff format` across the backend + a CI `ruff format --check` gate, and a `/public/providers` endpoint
so both web UIs render one shared set of operator names. **Real-Postgres integration/E2E verified
locally** (full payment flow with balanced double-entry, the concurrency race above, and durability +
reconciliation across an API restart).

## 2026-07-06 - USSD channel build-out (ADR 0010)
The feature-phone path was hardened end-to-end: **French menus by default** (ASCII-safe for GSM-7;
`DRCPAY_USSD_LANG`); **retry-friendly parsing** (a mistyped till/amount/choice re-prompts instead of
hanging up - the parser skips misses when re-reading the accumulated text; 3 misses on one field ends
the session); **amount hardening** (positive, ≤10,000 USD fat-finger cap, comma decimals accepted -
"10,50"); **on-net-aware closing messages** (same-network: "pay the merchant's till/number directly",
replay-stable; routed: "approve with your PIN"); replies kept under the ~180-char USSD ceiling (tested).
Transport hardening (security roadmap Gate A): **aggregator shared secret** (`X-USSD-Secret`,
constant-time; `DRCPAY_USSD_SHARED_SECRET` - production refuses to boot without it, local/sandbox stay
open for the console's dial simulator) and an in-process **per-msisdn rate limit** (15/min sliding
window → wire-format END). Tests cover retries, caps, on-net vs routed, replay idempotency, secret,
rate limit, and boot guard. Design recorded in [ADR 0010](adr/0010-ussd-aggregator-auth-and-rate-limit.md).

## 2026-07-06 - Merchant authentication + per-merchant authorization (Gate A)
`domains/auth/` (Argon2id password hashing via argon2-cffi; opaque sessions stored as SHA-256 with a
24h TTL; an in-process login throttle), in-memory + SQL stores (migration `e9b3c5d7f1a2`),
**`POST /auth/login` / `GET /auth/me` / `POST /auth/logout`**, and a `CurrentMerchant` dependency that
fences every merchant endpoint to the logged-in merchant (cross-merchant reads 404 - no id oracle; the
on-net **confirm** is owner-only; `POST /transactions` and `/charges` take the merchant from the
session, never the body). The two `qr.svg` endpoints stay session-exempt by design (`<img>` can't send
headers; QR content is public pay info). The shared `DRCPAY_BASIC_AUTH_PASSWORD` gates only the sandbox
demo shell (console static, docs, `/demo/*`) - production boots without it; sandbox still refuses to
boot without one. Demo logins are seeded (`seed.py`), printed at seed time, and listed by sandbox-only
`GET /demo/credentials` (the console login screen shows them). Remaining, related: rate limiting beyond
the login throttle, audit logging, session-store cleanup job (expired rows are lazily deleted on
resolve) - see the security roadmap.

## 2026-07-06 - On-net same-network: facilitate & record (ADR 0009)
We do NOT route or hold money on-net: the customer pays the merchant **directly on the operator's own
rail** (their till whenever they have one, else their number), and we **record & confirm** the sale -
non-custodial, no operator money-API, `fee=0`. Cross-network stays on pawaPay. "Paid" is tagged
**merchant-attested** (on-net) vs **rail-verified** (pawaPay).
- **Trim + backend flow.** Removed the operator-API machinery (`DirectCollectRail`, the `airtel`/`mpesa`
  scaffolds, `simulated_direct.py`, the `DRCPAY_ONNET_SIMULATE` toggle). `OnNetOrchestrator` is rail-free
  (records *awaiting confirmation* → `on_confirm` posts the one ledger entry, paid). `start_merchant_payment`
  routes same-network → on-net awaiting (all pairs, via `ON_NET_PROVIDERS` in `routing.py`).
  **`POST /transactions/{id}/confirm`** (merchant-gated; `?received=false` for not-received; idempotent)
  resolves it. A **`provenance`** field (`merchant_attested` | `rail_verified`) on the txn + responses,
  persisted via migration `a7c1e9f04b2d`. `/pay` exposes `on_net` + `pay_to_msisdn` + `pay_to_operator`.
- **UI slice.** Customer page: when `on_net`, a hand-off card - "pay `<merchant>` directly on `<operator>`"
  showing the merchant's **till** when set (else their number) + a live waiting state that polls
  `/public/transaction` until paid / not-received. Merchant console: a **"On-net - confirm receipt"** card
  listing awaiting on-net payments, each with **Confirm received** / **Not received**; those rows are kept
  out of the pawaPay reconcile safety-net, and the detail modal shows **assurance**. **Per-merchant
  operator till** added (`Merchant.operator_till`, migration `c3e8f1a9b7d2`, seeded on Alpha/Gamma, exposed
  via `/pay` `pay_to_till` + `/merchants`); `/pay` prefers it over the number.
- **To confirm with operators (not blocking the MVP):** the DRC "pay a merchant till" UX + tariff per
  operator, and whether tills emit a merchant-payment notification (the path to auto-confirm).

## 2026-07-05/06 - French localisation (i18n)
Both web UIs (merchant console + customer page, incl. its testing panels) carry an **FR|EN switch**:
French default, persisted in `localStorage["drcpay.lang"]`, every user-facing string externalised into
an in-page dictionary (static HTML via `data-i18n`, JS-built messages read it at render time). The
console's dark ops-trace panel intentionally stays English - it is a developer-style log and its line
prefixes drive the color coding. **USSD menu copy (2026-07-06):** the backend `ussd/` handler serves
French menus by default (`DRCPAY_USSD_LANG=en` flips a deployment; no in-menu language step - every extra
step costs completion). Menu strings are ASCII-only on purpose: GSM-7 USSD transports mangle accented
characters on some feature phones.
