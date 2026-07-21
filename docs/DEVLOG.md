# DRC Pay - Development Log & Handoff

**Last updated:** 2026-07-20 · **Read this first to resume work.**

**Product:** a **merchant-facing** app for the DRC: merchants accept mobile-money payments across
networks (Vodacom M-Pesa, Airtel, Orange) on **rented rails (pawaPay)** as a **pure pass-through**
(we never hold funds). Customers pay with **no app of their own** - they scan a merchant's charge QR,
or dial USSD. Research is the sibling `../drc-mvp-research/`; this repo (`drc-pay/`) is the app.

---

## TL;DR - where we are
- **🟢 LIVE on Railway, end-to-end on real pawaPay sandbox** (`https://drc-pay-sandbox-production.up.railway.app`;
  Postgres `drc-pay-db`; demo merchants auto-seeded). Real phone → scan a charge QR → pay → confirms
  **in real time** on both the payer's screen and the Merchant Console.
- **Signed callbacks (RFC-9421) wired & verifying** - deposit/payout outcomes arrive by push; the
  reconciliation sweep is the backstop. The pawaPay **v2 contract is confirmed** (see that section).
- **Scan-to-pay is a "charge" (checkout):** merchant posts an amount → a QR carries the charge id →
  the customer is charged exactly that (server-authoritative). The old static per-merchant QR is gone.
- **Real per-network-pair fees** (pawaPay published cost, **pass-through, no margin yet**) replaced the
  flat 1%; pawaPay's cost is now booked to **`expense:pawapay`** and `revenue:fees` holds only the
  **margin** (0 today) - ADR 0007. See "How the money works".
- **Backend green:** ruff + mypy --strict clean, **full test suite passing**. Payment spine (collect → settle →
  auto-refund), double-entry ledger, 10-state machine, idempotency, Merchant + Charge domains, Postgres
  + Alembic, pawaPay client/rail, signed-callback receiver, reconciliation sweep, USSD channel. **On-net
  = facilitate & record ([ADR 0009](adr/0009-on-net-facilitate-and-record.md)), backend DONE.**
  Same-network payments are paid **merchant-direct on the operator's own rail** (we never touch the
  money); we record an *awaiting-confirmation* txn, the merchant taps **Confirm received**, and it's
  marked paid (**merchant-attested**). The operator-API "direct-collect" approach is **retired** (it
  would make us the merchant → custody → EMI licence). The on-net **UI is now built** (customer hand-off,
  merchant Confirm-received, per-merchant till) - the slice is complete; see NEXT for the next rocks.
- **Web UIs:** **Merchant Console** (gated) - "Charge by QR", live feed, ledger drill-down, a
  de-emphasized reconcile fallback, and an **on-net "Confirm receipt"** card; **Customer page** (public) -
  scan → locked amount → pick network → pay, confirms live with the fee shown, or an **on-net hand-off**
  (pay the merchant directly on the operator - their till when set, else their number) when same-network.
  **Both web UIs are bilingual: French (default) / English**, via an FR|EN switch persisted per device.
- **Console is mobile-first with two views:** a plain **simple view** for merchants and a sandbox-only
  **dev view** (ops trace, simulators, force-reconcile, technical txn detail) behind a DEV toggle
  (2026-07-18; full write-up in [`history.md`](./history.md)).
- **Merchant auth + per-merchant authorization (Gate A) - DONE.** Every merchant signs in with their
  own account; the merchant API is session-gated in every environment and scoped to the session's
  merchant. The console has a login screen (demo accounts `alpha`/`beta`/`gamma`, password
  `<username>-demo`); the shared Basic password now gates only the sandbox demo shell.
- **Merchant self-onboarding - DONE ✅ (2026-07-21).** A business registers itself (`POST /signup` /
  the console's "Create an account" form) as a **pending** merchant that cannot log in or transact,
  and a **staff member** approves it in the new **Staff Console** (`/staff`) - so adding a merchant
  no longer means editing `seed.py`. Staff are a separate identity from merchants (`domains/staff/`).
  **KYC and a production admin-bootstrap remain open** - see NEXT.

## ▶ NEXT - biggest open rocks (rough priority; confirm the pick before building)

**Recently shipped** (full write-ups in [`history.md`](./history.md)): merchant authentication +
per-merchant authorization (Gate A), French i18n (web + USSD), on-net facilitate-and-record
(backend + UI, ADR 0009), the USSD channel build-out (ADR 0010), the post-USSD hardening/review
pass, and the mobile-first console with simple/dev views.

**Direction (2026-07-16):** the product is **merchant-centric** - customers pay by QR/USSD and need no
app awareness, so the **customer page stays intentionally minimal**; UI investment goes to the
**merchant console**. Beta path, in order: **(1) merchant self-onboarding** (the real unblock - you
can't add a merchant without editing `seed.py` today), **(2) a mobile-responsive pass on the merchant
console** (responsive web, *not* a native app yet) - **DONE ✅ (2026-07-18)**, see the mobile-first +
simple/dev-views TL;DR bullet - then **(3) Gate A security** - required only once
the beta moves *real* money (a sandbox beta with real merchants doesn't need it first). Confirm the
sandbox-vs-real-money fork before sequencing security ahead of UI.

1. **Merchant onboarding - DONE ✅ (2026-07-21); KYC still open.** A business can now register
   itself and be activated without anyone editing `seed.py` - the beta unblock. Self-onboarding with
   **manual approval**, gated by **staff/admin accounts**:
   - **Sign-up:** public `POST /signup` creates a **pending** merchant + its Argon2id login
     (`application/onboarding.py`), server-assigned id/short-code. A pending merchant is inert -
     login is gated on merchant status, and `is_active` already fenced take-payment/create-charge.
   - **Staff identity:** a separate `domains/staff/` (credentials with a role, opaque expiring
     sessions, own `drcpay_admin_session` cookie; migration `f1a2b3c4d5e6`), `POST /admin/login`.
     Cross-tier isolation is enforced and tested both ways.
   - **Approval:** `GET /admin/merchants?status=pending`, `POST /admin/merchants/{id}/approve` /
     `/reject` (admin role required).
   - **UIs:** a "Create an account" form on the merchant console login (bilingual FR/EN) and a
     **Staff Console** at `/staff` (`frontend/staff-console/`, `DRCPAY_STAFF_DIR`) - sign in, review
     sign-ups, approve/reject. English-only on purpose (internal operator tool).
   - **Staff account management - DONE ✅ (2026-07-21).** Three ways to mint an admin, sharing one
     validated create/upsert (`application/staff_accounts.py`):
     **(1) bootstrap** - set `DRCPAY_ADMIN_USERNAME` + `DRCPAY_ADMIN_PASSWORD` and every deploy
     creates-or-updates that one account **in every environment, production included** (idempotent
     by username, so changing the env var rotates the password instead of duplicating the account);
     **(2) CLI** - `python -m drc_pay_api.create_staff --username X` (prompts for the password, so
     it stays out of shell history) for ad-hoc creation and password resets;
     **(3) admin-creates-admin** - `GET`/`POST /admin/staff` plus an "Add a staff member" form in
     the Staff Console. That path is deliberately **create-only**: a taken username is a 409, never
     a silent password reset, so one admin can't take over another's account.
   - **Still open:** **KYC** (deferred by design).
2. **Rent a real USSD aggregator** (Africa's Talking / Infobip) when going live: shortcode + MNO PIN
   wiring; our `/ussd` handler is provider-neutral and ready (adapting the wire format is confined to
   `http/ussd_routes.py`). *(Also where the static-till QR returns.)*
3. **Production hardening** - AWS (Terraform, `af-south-1`, Secrets Manager - notes in `future-dev.md`); lock CORS to
   known origins. Reconciliation now runs on an in-process schedule on a live rail (`main.py`,
   `DRCPAY_RECONCILE_INTERVAL_SECONDS`); still open: an age filter + batch limit on the sweep. Minor:
   charge expiry (none yet); on-net rows have no ageing rule (sit awaiting-confirm indefinitely).
4. **Monetization model - not established (not urgent).** How we turn a profit isn't decided, and we may
   not take a per-transaction margin at first. Options to weigh: **(a) per-transaction margin** on the MDR -
   the ledger already supports it (set `mdr = cost + margin` in `pricing.py`; cost → `expense:pawapay`,
   surplus → `revenue:fees`; ADR 0005/0007); **(b) SaaS subscription** per merchant (flat or tiered monthly),
   likely the simplest first model; **(c) value-added / freemium** services later (analytics, faster payouts,
   lending). On-net stays `fee=0` regardless (ADR 0009) - any on-net monetisation is SaaS, never a rail cut.

---

## Architecture (hexagonal / ports-and-adapters)
Domain is pure; infra plugs in via ports; channels are thin callers.

```
backend/src/drc_pay_api/
├── domains/                  # PURE - no HTTP/SQL/vendor knowledge
│   ├── ledger/   money.py    # Money = integer minor units (never floats)
│   │             ledger.py   # double-entry Posting/Entry (must balance)
│   ├── merchants/ models.py  # Merchant (id, name, till, settlement acct)
│   ├── charges/  models.py   # Charge (merchant-posted amount); status DERIVED from its payment
│   └── transactions/  state_machine.py models.py orchestrator.py ports.py
│                      pricing.py   # real per-(payer,merchant)-network-pair fee, pass-through
├── application/  payments.py # start_merchant_payment - shared by every channel; computes the fee
│               outcomes.py   # apply_outcome - ONE leg-resolver (webhook + sweep)
│               webhooks.py · payment_codes.py
├── adapters/  memory.py sql.py   # in-memory + SQLAlchemy/Postgres stores (tx, ledger, merchant, charge)
├── integrations/pawapay/    # client · rail · providers · signatures · callbacks · status · simulator
├── ussd/  session.py        # USSD channel: full-text parse + dial fast-path
├── jobs/reconciliation/sweep.py   # missed-callback safety net → apply_outcome
├── container.py              # composition root - every channel wires through it (not under http/)
├── http/   schemas.py dependencies.py (FastAPI glue injecting the container)
│           merchant_api.py    # transactions + merchants + charges (one merchant trust tier)
│           auth_routes.py           # merchant login/logout/me (session-gated)
│           onboarding_routes.py     # public POST /signup — self-onboarding (pending merchant)
│           admin_routes.py admin_merchants_routes.py  # staff login + merchant approve/reject
│           ussd_routes.py webhook_routes.py
│           demo_routes.py     # /demo/reconcile - off-real-money path only (404 in prod)
│           public_routes.py   # /public/{merchant,charge,transaction}, /pay - public (sandbox-gated)
├── main.py · config.py · seed.py   # seed.py = demo-merchant seeding (entrypoint, sandbox/local)
frontend/ merchant-console/   # gated cockpit: Charge-by-QR, take-payment, live feed, sign-up form
          customer-app/       # public scan-to-pay (charge-driven) + USSD dial sim
          staff-console/      # internal /staff: staff login → approve/reject merchant sign-ups
Dockerfile                              # deploy (single container, on Railway)
```
**Layering:** dependencies point inward; `domains/` + `application/` never import a channel.

---

## How the money works (verified by tests)
Customer pays the sticker `amount`; the merchant **absorbs the fee (MDR)** and nets `amount − fee`.
pawaPay's round-trip cost is booked to **`expense:pawapay`** (per leg, as each completes); whatever is
left of the MDR after cost - the **margin** - goes to **`revenue:fees`**. With **no margin set yet the
MDR equals cost, so revenue is exactly 0** and expense carries the whole fee (we keep nothing). A
post-collection failure **refunds the customer in full** - the sunk collection fee stays in expense, a
real loss; a failed refund → `manual_review`. Money is **integer minor units**; the double-entry ledger
is the source of truth (every posting balances). See **ADR 0007** (cost is an expense, not revenue).

**Fee = real pawaPay round-trip cost for the network pair** (`pricing.py`): collect fee on the payer's
operator + payout fee on the merchant's (Vodacom 2.5/2.0, Airtel 3.0/2.0, Orange 3.0/1.0 - collect/payout
%), i.e. 3.5–5.0% per pair. The MDR **passes that cost straight through - no margin yet**; margin is the
open pricing decision (ADR 0005; research `fees-and-costs.md`).

## Charges (checkout) - the scan-to-pay path
Merchant posts an amount → `POST /charges` → a `Charge` + a QR encoding `/customer/?charge=<id>`. The
customer who scans it pays exactly that (`POST /pay {charge_id}` - amount + merchant taken from the
charge, never the client; the txn links back; double-pay rejected). A charge's status is **derived** from
its linked transaction (no stored status to drift): awaiting → processing → paid / declined / refunded.
Console "Charge by QR" creates one and polls it live; the public `GET /public/charge/{id}` feeds the
payer page.

## pawaPay - the integration (v2, live-callback-verified)
- **Async:** `POST /v2/{deposits,payouts,refunds}` → ACCEPTED/REJECTED; final outcome via a **signed
  callback (RFC-9421)** or polling `GET /v2/.../{id}`. Push (webhook) + poll (sweep) both resolve a leg
  through one `apply_outcome` (state-guarded, idempotent).
- **Contract CONFIRMED (docs + real callbacks):** callback body is **FLAT** (top-level
  `depositId`/`payoutId`/`refundId` + `status`); the **status endpoint wraps** under
  `{"status":"FOUND","data":{…}}`. Terminal = `COMPLETED`/`FAILED`; others → PENDING (fail-safe).
  Signatures: ECDSA-P256, components `@method @authority @path signature-date content-digest content-type`,
  label `sig-pp`; pawaPay sends **DER** (~70 bytes) - `signatures.py` accepts DER + raw-64. Public key is
  **auto-fetched** from `GET /v2/public-key/http` at startup (override via `DRCPAY_PAWAPAY_PUBLIC_KEY`).
- ⚠️ **Token gotcha:** must be a **sandbox** token (matches `api.sandbox.pawapay.io`); a live token reads
  "invalid". Paste cleanly in Railway (no quotes/whitespace/`Bearer `). Quick manual check that a token
  authenticates (read-only, no money moved): `python tests/pawapay_smoke.py` (reads `.env`; see its docstring).
- **DRC providers:** `VODACOM_MPESA_COD`, `AIRTEL_COD`, `ORANGE_COD`. USD = 2 decimals; Vodacom CDF = 0.
  **Sandbox test numbers:** operator prefix + last-3-digit outcome (`…789` success, `…049` insufficient):
  Vodacom `243813456789`, Airtel `243973456789`, Orange `243893456789` (docs.pawapay.io/v2/docs/test_numbers).
  Open: replace the static `_DECIMALS` map with live `active-conf`.
- **Live-sandbox e2e tests** (`tests/test_pawapay_sandbox_e2e.py`): opt-in (`RUN_PAWAPAY_SANDBOX_E2E=1`),
  off by default so the suite stays offline. They validate the seam the simulator can't: real auth,
  the callback key loads as **EC P-256**, the status envelope, deposit acceptance + lifecycle
  (`…789` success / `…049` fail), the rail port, refund. Found a real constraint the simulator
  doesn't enforce: **VODACOM_MPESA_COD amounts must be 500 < x < 1,000,000 CDF**.

## Deploy - 🟢 LIVE on Railway
- One `Dockerfile`: install API → `alembic upgrade head` → **seed demo merchants** (`python -m
  drc_pay_api.seed`, sandbox/local only; **production starts empty**) → uvicorn (`--proxy-headers`),
  serving the API + gated `/console` + public `/customer`. `DRCPAY_BASIC_AUTH_PASSWORD` gates all but the
  customer paths, the webhook, and `/health`.
- ⚠️ **`DRCPAY_DATABASE_URL` must be a working reference** (`${{drc-pay-db.DATABASE_URL}}`, **no quotes**)
  or the app silently runs in-memory and the DB stays empty. Verify: deploy logs show migrations +
  `[seed] demo merchants ready`; the Data tab has tables.
- ⚠️ **Boot-required secrets (fail closed):** `sandbox` will not start without `DRCPAY_BASIC_AUTH_PASSWORD`
  (its demo shell would be public); **`production` will not start without `DRCPAY_USSD_SHARED_SECRET`**
  (the public `/ussd` payment endpoint would accept prompts from anyone). Set each in the dashboard
  before deploying that environment. An unrecognized `DRCPAY_ENVIRONMENT` also refuses to boot, so a
  typo like `prod` fails closed instead of silently skipping these gates.
- **On-net (same-network):** routed automatically (all same-network pairs, per `routing.py`) - recorded
  as *awaiting confirmation*, no rail, no money movement; the merchant taps **Confirm received** to mark
  it paid (merchant-attested). No toggle: on-net is always facilitate & record (ADR 0009).
- **AWS is the eventual production target** (notes in `future-dev.md`); the Docker image is portable. Alembic head:
  `f1a2b3c4d5e6` (adds `staff_credentials` + `staff_sessions` for admin accounts).

---

## Open items / TODOs
**Security items now live in [`security-roadmap.md`](./security-roadmap.md)** (the staged checklist:
merchant auth, per-merchant authorization, USSD hardening, rate limits, CORS, charge expiry, audit
logging gate the first real-money pilot; PII encryption, KYC, monitoring gate production).
Non-security items:
**USSD channel build-out + tests** (above - the next priority) · **real USSD aggregator** ·
**reconciliation age filter + batch limit** (now scheduled in-process on a live rail;
the unbounded `find_pending` scan is the remaining gap) · **native mobile app** (deferred,
web-first) · **refund-leg fee** (pawaPay bills refunds ≈
the disbursement rate - Plans page; our refund path books only the sunk collection fee, and whether
pawaPay reverses that collection fee is unconfirmed; research `fees-and-costs.md`) · **monetization model**
(above - not urgent; margin vs subscription vs VAS) · **Legal/licensing (BCC)** - standing flag.

**Longer-horizon / someday** (mobile app · admin dashboard · AWS infra · splitting the webhook receiver
into its own service): see [`future-dev.md`](./future-dev.md).

## How to run
```bash
cd backend && source .venv/bin/activate
ruff check . && mypy src && pytest                          # all green (offline; sandbox tests skip)
# opt-in live sandbox e2e (real network, sandbox only): RUN_PAWAPAY_SANDBOX_E2E=1 pytest tests/test_pawapay_sandbox_e2e.py
export DRCPAY_CONSOLE_DIR="$PWD/../frontend/merchant-console"
export DRCPAY_CUSTOMER_DIR="$PWD/../frontend/customer-app"
export DRCPAY_STAFF_DIR="$PWD/../frontend/staff-console"     # Staff Console at /staff (approvals)
uvicorn --app-dir src drc_pay_api.main:app                  # console /console/ ; pay via "Charge by QR"
# console login (per-merchant auth): alpha / alpha-demo (also beta, gamma - password <username>-demo)
# admin login (staff, sandbox/local only): admin / admin-demo — approves self-onboarded merchants
#   real staff accounts: DRCPAY_ADMIN_USERNAME/_PASSWORD (every env, incl. production), or
#   `python -m drc_pay_api.create_staff --username X`, or the Staff Console's "Add a staff member"
# self-onboarding: POST /signup (public) -> pending merchant; admin approves via /admin/merchants/{id}/approve
# live sandbox rail: token in backend/.env (DRCPAY_PAWAPAY_BASE_URL + _API_TOKEN) → off the simulator.
# Postgres: docker compose up -d ; export DRCPAY_DATABASE_URL=… ; alembic upgrade head
# Integration / E2E against REAL Postgres (durability, concurrency, reconciliation): bring up
# Postgres as above, keep the in-process simulator rail (leave DRCPAY_PAWAPAY_* unset) for
# deterministic synchronous payouts, then drive /auth/login → /charges → /pay and read rows with
# `docker compose exec -T postgres psql -U drcpay -c "select … from transactions/ledger_entries"`.
```
**Gotcha:** the repo path has a space → pip *editable* installs break. Run uvicorn with `--app-dir src`;
tests use `pythonpath=src`.

## Git & conventions
Repo **github.com/TristanDS95/drc-pay** (`main`); **the human pushes**; commits use **no** Claude
co-author trailer; Conventional Commits; keep ruff + mypy + pytest green. **`CLAUDE.md`** is the
engineering standards, now tracked in-repo. Plain-language tour: `docs/architecture-guide.md` (source;
the `.docx` is generated from it via pandoc). ADRs in `docs/adr/`. Simplicity: `docs/simplicity-review.md`.

## Carry-forward insights
1. **Money core is role- and channel-agnostic** - every channel (HTTP, USSD, charge) is a thin caller
   into `start_merchant_payment`; ledger/state-machine/orchestrator are written once.
2. **pawaPay is async** - callback (push) and sweep (poll) both resolve via one `apply_outcome`.
3. **Tests catch real bugs** and stay offline/deterministic via the in-process simulator.
4. **Invest in the money core; flag honest gaps rather than gold-plate.**
```
