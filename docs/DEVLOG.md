# DRC Pay - Development Log & Handoff

**Last updated:** 2026-07-18 · **Read this first to resume work.**

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
- **Merchant console: mobile-first + simple/dev views - DONE ✅ (2026-07-18).** The console is now
  mobile-first (one-column phone layout, 48px touch targets, the charge → QR → confirm-receipt flow up
  top; desktop widens to actions | feed) and ships **two views**: the plain **simple view** every
  merchant sees (hero, Charge by QR, USSD sticker, on-net confirm, pending count, feed) and a
  **dev view** (ops trace, take-payment + USSD dial simulators, force-reconcile, technical txn detail:
  pawaPay op ids / state history / ledger) behind a **DEV toggle**. Gating is CSS-only (`[data-dev]` /
  `[data-simple]` on one shared page - no duplicated markup to drift) and the toggle renders only where
  `/demo/*` exists (local/sandbox), so production merchants can never reach the diagnostic view.
- **Merchant auth + per-merchant authorization (Gate A) - DONE.** Every merchant signs in with their
  own account; the merchant API is session-gated in every environment and scoped to the session's
  merchant. The console has a login screen (demo accounts `alpha`/`beta`/`gamma`, password
  `<username>-demo`); the shared Basic password now gates only the sandbox demo shell.

## ▶ NEXT - biggest open rocks (rough priority; confirm the pick before building)

**Merchant authentication + per-merchant authorization - DONE ✅ (2026-07-06).**
`domains/auth/` (Argon2id password hashing via argon2-cffi; opaque sessions stored as SHA-256 with a
24h TTL; an in-process login throttle), in-memory + SQL stores (migration `e9b3c5d7f1a2`),
**`POST /auth/login` / `GET /auth/me` / `POST /auth/logout`**, and a `CurrentMerchant` dependency that
fences every merchant endpoint to the logged-in merchant (cross-merchant reads 404 - no id oracle; the
on-net **confirm** is owner-only; `POST /transactions` and `/charges` take the merchant from the
session, never the body). The two `qr.svg` endpoints stay session-exempt by design (`<img>` can't send
headers; QR content is public pay info). The shared `DRCPAY_BASIC_AUTH_PASSWORD` gates only the
sandbox demo shell (console static, docs, `/demo/*`) - production boots without it; **sandbox still
refuses to boot without one**. Demo logins are seeded (`seed.py`), printed at seed time, and listed by
sandbox-only `GET /demo/credentials` (the console login screen shows them). Remaining, related:
rate limiting beyond the login throttle, audit logging, session-store cleanup job (expired rows are
lazily deleted on resolve) - see the security roadmap.

**French localisation (i18n) - web UIs DONE ✅ (2026-07-05); backend USSD copy DONE ✅ (2026-07-06).**
Both web UIs (merchant console + customer page, incl. its testing panels) carry an **FR|EN switch**:
French default, persisted in `localStorage["drcpay.lang"]`, every user-facing string externalised into
an in-page dictionary (static HTML via `data-i18n`, JS-built messages read it at render time).
The console's dark ops-trace panel intentionally stays English - it is a developer-style log and its
line prefixes drive the color coding.
**USSD menu copy: also done ✅ (2026-07-06)** - the backend `ussd/` handler serves French menus by
default (`DRCPAY_USSD_LANG=en` flips a deployment; no in-menu language step - every extra step costs
completion). Menu strings are ASCII-only on purpose: GSM-7 USSD transports mangle accented characters
on some feature phones.

**On-net same-network - "facilitate & record" ([ADR 0009](adr/0009-on-net-facilitate-and-record.md)); backend + UI DONE.**
We do NOT route or hold money on-net: the customer pays the merchant **directly on the operator's own
rail** (their till whenever they have one, else their number), and we **record & confirm** the sale -
non-custodial, no operator money-API, `fee=0`. Cross-network stays on pawaPay. "Paid" is tagged
**merchant-attested** (on-net) vs **rail-verified** (pawaPay).
- **DONE - trim + backend flow ✅ (full suite green).** Removed the operator-API machinery
  (`DirectCollectRail`, the `airtel`/`mpesa` scaffolds, `simulated_direct.py`, the `DRCPAY_ONNET_SIMULATE`
  toggle). `OnNetOrchestrator` is rail-free (records *awaiting confirmation* → `on_confirm` posts the one
  ledger entry, paid). `start_merchant_payment` routes same-network → on-net awaiting (all pairs, via
  `ON_NET_PROVIDERS` in `routing.py`). **`POST /transactions/{id}/confirm`** (merchant-gated;
  `?received=false` for not-received; idempotent) resolves it. A **`provenance`** field
  (`merchant_attested` | `rail_verified`) on the txn + responses, persisted via migration
  `a7c1e9f04b2d`. `/pay` exposes `on_net` + `pay_to_msisdn` + `pay_to_operator` for the hand-off.
- **DONE - the UI slice ✅.** Customer page (`frontend/customer-app`): when `on_net`, a hand-off card -
  "pay `<merchant>` directly on `<operator>`" showing the merchant's **till** when set (else their number) +
  a live waiting state that polls `/public/transaction` until paid / not-received. Merchant console
  (`frontend/merchant-console`): a **"On-net - confirm receipt"** card listing awaiting on-net payments,
  each with **Confirm received** / **Not received** → `POST /transactions/{id}/confirm`; those rows are kept
  out of the pawaPay reconcile safety-net, and the detail modal shows **assurance** (merchant-attested vs
  rail-verified). **Per-merchant operator till** added (`Merchant.operator_till`, migration `c3e8f1a9b7d2`,
  seeded on Alpha/Gamma, exposed via `/pay` `pay_to_till` + `/merchants`); `/pay` prefers it over the number.
- **To confirm with operators (not blocking the MVP):** the DRC "pay a merchant till" UX + tariff per
  operator, and whether tills emit a merchant-payment notification (the path to auto-confirm).

**USSD channel build-out - DONE ✅ (2026-07-06).** The feature-phone path is now hardened end-to-end:
**French menus by default** (ASCII-safe for GSM-7; `DRCPAY_USSD_LANG`); **retry-friendly parsing** (a
mistyped till/amount/choice re-prompts instead of hanging up - the parser skips misses when re-reading
the accumulated text; 3 misses on one field ends the session); **amount hardening** (positive, ≤10,000
USD fat-finger cap, comma decimals accepted - "10,50"); **on-net-aware closing messages** (same-network:
"pay the merchant's till/number directly", replay-stable; routed: "approve with your PIN"); replies kept
under the ~180-char USSD ceiling (tested). Transport hardening (security roadmap Gate A): **aggregator
shared secret** (`X-USSD-Secret`, constant-time; `DRCPAY_USSD_SHARED_SECRET` - production refuses to
boot without it, local/sandbox stay open for the console's dial simulator) and an in-process
**per-msisdn rate limit** (15/min sliding window → wire-format END) so nobody sprays payment prompts at
arbitrary numbers. Tests cover retries, caps, on-net vs routed, replay idempotency, secret, rate limit,
and boot guard. Design recorded in [ADR 0010](adr/0010-ussd-aggregator-auth-and-rate-limit.md).

**Post-USSD hardening & review pass - DONE ✅ (2026-07-16).** A max-effort review of the USSD channel
surfaced 17 findings; the money- and security-critical ones were fixed and adversarially re-verified.
Highlights: **idempotency is now atomic in the application layer** - `start_merchant_payment` owns a
find-or-create backed by the store's unique `idempotency_key` constraint (a concurrent double-submit
yields exactly one transaction, never a double charge or a 500; verified with a 12-thread race against
real Postgres). **Strict typed-amount parsing** (`Money.from_user_input` rejects thousands-grouped /
scientific-notation / Unicode-digit input instead of silently misreading it). **msisdn hardening**
(`fullmatch` + ASCII digits; `+`/no-`+` normalised to one identity for the rate-limit bucket and the
idempotency key). **Fail-closed boot** on an unrecognised `DRCPAY_ENVIRONMENT` (a typo like `prod` no
longer skips the safety gates). Plus dead-code prune, `ruff format` across the backend + a CI
`ruff format --check` gate, and a `/public/providers` endpoint so both web UIs render one shared set of
operator names. **Real-Postgres integration/E2E verified locally** (full payment flow with balanced
double-entry, the concurrency race above, and durability + reconciliation across an API restart) - see
"How to run".

**Direction (2026-07-16):** the product is **merchant-centric** - customers pay by QR/USSD and need no
app awareness, so the **customer page stays intentionally minimal**; UI investment goes to the
**merchant console**. Beta path, in order: **(1) merchant self-onboarding** (the real unblock - you
can't add a merchant without editing `seed.py` today), **(2) a mobile-responsive pass on the merchant
console** (responsive web, *not* a native app yet) - **DONE ✅ (2026-07-18)**, see the mobile-first +
simple/dev-views TL;DR bullet - then **(3) Gate A security** - required only once
the beta moves *real* money (a sandbox beta with real merchants doesn't need it first). Confirm the
sandbox-vs-real-money fork before sequencing security ahead of UI.

1. **Merchant onboarding + KYC** - merchants are seeded (`seed.py`); need a create/manage flow + KYC (no
   onboarding UI/API; no DB FK on `merchant_id`). **Now the top beta priority** (see Direction above).
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
│           ussd_routes.py webhook_routes.py
│           demo_routes.py     # /demo/reconcile - off-real-money path only (404 in prod)
│           public_routes.py   # /public/{merchant,charge,transaction}, /pay - public (sandbox-gated)
├── main.py · config.py · seed.py   # seed.py = demo-merchant seeding (entrypoint, sandbox/local)
frontend/ merchant-console/   # gated cockpit: Charge-by-QR, take-payment, live feed
          customer-app/       # public scan-to-pay (charge-driven) + USSD dial sim
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
  `e9b3c5d7f1a2` (adds `merchant_credentials` + `merchant_sessions`).

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
uvicorn --app-dir src drc_pay_api.main:app                  # console /console/ ; pay via "Charge by QR"
# console login (per-merchant auth): alpha / alpha-demo (also beta, gamma - password <username>-demo)
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
