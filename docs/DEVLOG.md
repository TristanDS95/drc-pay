# DRC Pay — Development Log & Handoff

**Last updated:** 2026-06-12 · **Read this first to resume work.**

This is the running state of the build. **The product (post-pivot): a merchant-facing
app for the DRC** that lets merchants **accept mobile-money payments across networks**
(Vodacom M-Pesa, Airtel, Orange) on **rented rails (pawaPay)** as a **pure pass-through**
(we never hold funds). Merchants get a clean app/dashboard; **customers pay via the
merchant app or USSD and need no app of their own**. A consumer-facing version may come
later. Initial launch: ~40 gas stations + pop-up stores. Research lives in the sibling
`../drc-mvp-research/`; this repo (`drc-pay/`) is the app.

> **Pivot note (2026-06-11):** we moved from a *consumer* "pay any number" app to a
> *merchant-acquiring* app. The money core was role-agnostic, so this was mostly a
> reframe (customer→merchant), a fee-model change (merchant absorbs the MDR), a new
> Merchant domain, and the new **USSD channel** (now MVP-critical, not v2). See
> "Merchant pivot" below.

---

## TL;DR — where we are
- **Backend (`services/api`)** is well underway and fully green: ruff + mypy --strict
  clean, **109 tests passing**. Built: the payment spine, the **Merchant domain**, the
  **MDR fee model**, Postgres persistence, Alembic migrations, idempotency, the pawaPay
  outbound client **wired into the orchestrator**, a first-class **USSD channel**,
  **customer-initiated QR/USSD payments** (per-merchant payment codes + a printable QR), the
  **pawaPay callback receiver** (Phase D.1: signed-webhook verify → reconcile into state), and
  the **reconciliation sweep** (Phase D.2: poll pawaPay's status endpoints to heal missed callbacks).
- **Channels:** the **USSD channel** (customer-initiated — the customer scans the
  merchant's QR or dials the till; the **primary** retail flow) and the **HTTP API** (the
  merchant app/dashboard, incl. a merchant-initiated *charge-by-number* push **fallback**)
  are both thin callers into the *same* orchestrator via `application.start_merchant_payment`.
- **Mobile app (`apps/mobile`)**: not started (only `theme/tokens.ts`). **Decision: web-first**
  for the merchant interface — native Expo Android is deferred until Phase E proves the live
  rails. The **Merchant Console** (`tooling/merchant-console`) is the web cockpit — take payments,
  a live feed, the **reconciliation safety net** with a "run it now" button, and a
  ledger/state-history drill-down; wired to all real endpoints (sandbox).
- **Immediate next:** **Phase D (callbacks + reconciliation) is done** — D.1 the signed-webhook
  receiver, D.2 the reconciliation sweep (polls pawaPay status endpoints to heal *missed*
  callbacks). Next is the **real USSD aggregator** + **merchant onboarding**, and the live
  sandbox test (Phase E, needs credentials), which also confirms the *provisional* callback +
  status-endpoint JSON shapes.

---

## Architecture (hexagonal / ports-and-adapters)
The domain is pure; infrastructure plugs in via ports; channels are thin callers. This
has repeatedly paid off (in-memory → Postgres with **zero** domain changes; the merchant
pivot reused the whole money core; USSD is just another caller).

```
services/api/src/drc_pay_api/
├── domains/                     # PURE — no HTTP/SQL/vendor knowledge
│   ├── ledger/  money.py        # Money = integer minor units (never floats)
│   │            ledger.py       # double-entry Posting/Entry (must balance)
│   ├── merchants/ models.py     # Merchant (id, name, short_code/till, settlement acct)
│   └── transactions/
│        state_machine.py        # 10-state machine; illegal transitions raise
│        models.py               # Transaction (customer/merchant, amount, fee, state, …)
│        orchestrator.py         # THE SPINE: collect→settle→refund; emits a trace
│        ports.py                # PaymentRail, TransactionStore, LedgerPort, Recorder
│        pricing.py              # default_fee = 1% MDR (placeholder)
├── application/  payments.py    # start_merchant_payment — shared by every channel
│               payment_codes.py # per-merchant USSD string / tel: URI (the QR payload)
│               webhooks.py      # process_pawapay_callback — verify → correlate → apply
│               outcomes.py      # apply_outcome — ONE leg-resolver shared by webhook + sweep
├── adapters/
│   ├── memory.py                # in-memory stores/ledger/recorder (demo + tests)
│   └── sql.py                   # SQLAlchemy 2.0 Postgres stores + ledger
├── integrations/pawapay/
│   ├── client.py                # PawaPayClient (deposits/payouts/refunds/predict + status GETs)
│   ├── providers.py             # DRC codes + provider_decimals/format_amount
│   ├── rail.py                  # PawaPayRail — client → PaymentRail port
│   ├── signatures.py            # verify RFC-9421 / ECDSA-P256 callback signatures
│   ├── callbacks.py             # parse a callback → CallbackEvent (provisional shape)
│   ├── status.py                # async-status vocab: Outcome/classify + StatusPoller (push+poll)
│   └── simulator.py             # SimulatedPaymentRail — now models async: issues op-ids + StatusPoller
├── ussd/  session.py            # USSD channel: full-text parse + QR/dial fast-path → orchestrator
├── http/  routes.py schemas.py container.py ussd_routes.py merchant_routes.py webhook_routes.py
│         demo_routes.py         # /demo/reconcile — simulator-only control for the console (404 in prod)
├── jobs/reconciliation/sweep.py # Phase D.2 — poll status endpoints → apply_outcome for missed callbacks
├── main.py                      # create_app() factory; module-level `app`
└── config.py                    # 12-factor settings (DRCPAY_* env vars)
migrations/                      # Alembic (5: baseline → idempotency → pawaPay ids →
                                 #   merchants table → merchant-pivot rename)
tests/                           # 109 tests (offline; conftest.py isolates the local .env)
```

**Layering rule:** dependencies point inward. `domains/` and `application/` never import
a channel (`http/`, `ussd/`). Channels depend on `application/` + `domains/`. (Note:
`http/container.py` is the app-wide composition root despite its folder — it could move to
a neutral location later; the USSD handler imports the `Container` type from it.)

---

## Channels (both are thin callers — never reimplementations)
Per our standards, the money logic is written once and every channel calls it:

- **HTTP API** (`http/routes.py`): `POST /transactions` records a customer paying a
  registered merchant. Resolves the merchant (server-derived settlement), then delegates
  to `application.start_merchant_payment`. Plus `GET /transactions[/{id}]`, `GET /health`,
  `/docs`. Demo `scenario` + `Idempotency-Key` header supported.
- **USSD channel** (`ussd/session.py` + `http/ussd_routes.py`): `POST /ussd` parses the
  aggregator's **full accumulated `text`** (`till*amount*choice`) positionally — no
  server-side session — and on confirm calls the **same** `start_merchant_payment`. This
  makes the **QR/dial fast-path** fall out: a scanned/dialed `*123*1001#` arrives as
  `text="1001"` (→ ask amount) and `*123*1001*10#` as `text="1001*10"` (→ straight to
  Confirm). Provider-neutral + offline-testable (`run_session` simulates an aggregator).
  The **real USSD aggregator** (wire format, shortcode, MNO PIN auth) is a **flagged team
  action** — researched in `../drc-mvp-research/02-findings/cross-cutting/ussd-gateway-providers.md`
  (lean: rent Africa's Talking / Infobip; don't self-host). A USSD payment lands in the
  same store → visible in the merchant's `/transactions` view.
- **Merchant codes + QR** (`http/merchant_routes.py`, `application/payment_codes.py`):
  `GET /merchants[/{id}]` returns each merchant's `ussd_string` (`*123*1001#`) and `tel_uri`
  (`tel:*123*1001%23`); `GET /merchants/{id}/qr.svg` is a printable QR (via `segno`) of the
  `tel:` dial-through. A merchant sticker shows the **QR + the dialable till**: a customer
  scans (Android) or dials it manually (iOS / feature phones). Shortcode is configurable
  (`DRCPAY_USSD_SHORTCODE`, placeholder `*123#`).

`application.start_merchant_payment` owns the shared glue: resolve each wallet's operator
(override → predict-provider → demo), start the two legs on the `Orchestrator`, and (on
the simulator) play out a demo outcome.

---

## Built & verified (ruff + mypy --strict clean, 109 tests)
- **Payment spine** (`orchestrator.py`): collect from the customer → settle to the
  merchant (merchant nets amount−fee; fee→revenue) → on settlement failure, auto-refund
  the customer the **full amount**; collection failure moves nothing; failed refund →
  `manual_review`. Every step enforced by the state machine and recorded as a balanced
  ledger posting.
- **Merchant domain** (`domains/merchants/`): a lightweight `Merchant` (id, name,
  short_code/till, settlement msisdn+provider, status); `MerchantStore` (in-memory + SQL).
  Two demo merchants are seeded for the zero-setup demo/tests (`m_alpha` Alpha Gas Station
  till `1001`; `m_beta` Beta Pop-up Store till `1002`).
- **MDR fee model**: the customer pays the sticker `amount`; the merchant **absorbs** our
  fee and nets `amount − fee`; we keep `fee` (booked to revenue only on a successful
  settlement). A refund returns the **full `amount`** to the customer.
- **HTTP API + USSD channel** (see "Channels"). Response includes an operations **trace**.
- **pawaPay callback receiver** (Phase D.1 — `application/webhooks.py`, `http/webhook_routes.py`,
  `integrations/pawapay/signatures.py` + `callbacks.py`): `POST /webhooks/pawapay` verifies the
  **RFC-9421 / ECDSA-P256** signature (Content-Digest + Signature, public-key) against
  `DRCPAY_PAWAPAY_PUBLIC_KEY`, correlates by op-id (`find_by_op_id`), and applies the outcome via
  the shared `application/outcomes.apply_outcome` (**state-guarded** → idempotent against resends).
  A synchronous rail **REJECT** (`RailRejected`) now maps to an immediate leg failure. Signature
  scheme verified offline (self-generated key); the callback **JSON body shape is provisional**
  (confirm in Phase E). New dep: `cryptography`.
- **Reconciliation sweep** (Phase D.2 — `jobs/reconciliation/sweep.py`, `application/outcomes.py`,
  `integrations/pawapay/status.py`): the safety net for **missed** callbacks. `reconcile_pending`
  finds every transaction in a **pending** state (`store.find_pending()`), polls pawaPay's
  deposit/payout/refund **status endpoint** (new `PawaPayClient` GET methods) for the awaited leg,
  and on a *terminal* status drives the **same `apply_outcome`** a callback would — so push and
  poll resolve a leg identically. It is **idempotent** (same state-guard; a callback that wins the
  race is a no-op), **fail-safe** (any status it can't read as terminal leaves the transaction
  untouched), and **robust** (one bad poll is recorded, not fatal). Returns a per-tx
  `ReconciliationSummary`. Offline-tested against a mocked status poller + `httpx.MockTransport`.
- **Postgres persistence** (`sql.py`): `transactions`, append-only `ledger_entries`,
  `merchants`; switchable via `DRCPAY_DATABASE_URL` (set → Postgres, blank → in-memory).
- **Alembic migrations** (5): baseline (`d11f02bd69d8`) → idempotency (`b79d18ed3797`) →
  pawaPay ids/providers (`c0a7b1d9e3f2`) → merchants table (`d1e2f3a4b5c6`) → merchant
  pivot rename customer/merchant + `merchant_id` (`e2f3a4b5c6d7`).
- **Idempotency**: `Idempotency-Key` header + unique DB constraint; a repeat key returns
  the original transaction (no double-charge).
- **pawaPay client + rail** (`client.py`, `rail.py`): deposits/payouts/refunds +
  `predict_provider` + provider-aware decimals; `PawaPayRail` generates UUIDv4 op-ids,
  returns them (orchestrator persists `deposit_id`/`payout_id`/`refund_id` + resolved
  `customer_provider`/`merchant_provider`), raises on a non-ACCEPTED ack.
- **Customer-initiated QR/USSD** (`application/payment_codes.py`, `http/merchant_routes.py`):
  per-merchant `ussd_string`/`tel_uri` + a printable `qr.svg` (segno); the USSD handler's
  dial-through fast-path lets a scan/dial land straight on Confirm. Customer-initiated pull
  is the **primary** retail flow; merchant-initiated charge-by-number is the kept **fallback**.
- **Web Merchant Console** (`tooling/merchant-console`): the current dev tracker — a single
  self-contained page wired to all real endpoints. Take a payment (instant *or* "await
  confirmation"), a live payments feed, the **reconciliation safety net** (pending count + a
  "Run reconciliation now" button that heals stuck payments leg-by-leg, traced live), and a
  per-transaction **ledger + state-history drill-down**. Responsive + a basic PWA manifest.
  To make the safety net demonstrable offline the **simulator now models pawaPay's async
  reality** (issues op-ids, implements `StatusPoller`); a `defer` flag on `POST /transactions`
  leaves a payment pending (a stand-in for a missed callback), and the **off-real-money-path**
  `POST /demo/reconcile` (mounted on the simulator or sandbox; 404 in production) runs the sweep.

---

## Money & fee behavior (confirmed correct)
- Fee = **1% MDR placeholder** (`pricing.py`); `start_transaction` requires `fee < amount`.
- The **customer pays exactly the sticker `amount`** (no fee on top); the **merchant nets
  `amount − fee`**; we keep `fee`, booked to revenue **only** on a successful settlement.
- On **any** failure after collection, the **customer** is refunded the **full `amount`**
  (no fee charged). Ledger postings (verified in tests):
  - Collect: `customer` debit **amount** · `clearing` credit **amount**
  - Settle: `clearing` debit **amount** · `merchant` credit **amount−fee** · `revenue` credit **fee**
  - Refund: `clearing` debit **amount** · `customer` credit **amount**
- *Cost note (later):* a failed settlement still incurred pawaPay's collection cost — we'd
  absorb that as cost-of-goods (P&L), not pass it to the customer or merchant.
- ⚠️ **Pricing unresolved — the 1% MDR is a placeholder *below cost*.** pawaPay's round-trip
  cost is **~3.5–5%**, so at 1% we **lose ~$0.53–$0.83 per $20 transaction**; the real MDR
  must cover all-in cost + margin (**≈5–7%+**), and the flat ~$0.034 USSD session fee makes
  small tickets worse (regressive). Decision pending — see **ADR 0005** and
  `../drc-mvp-research/02-findings/cross-cutting/fees-and-costs.md` + `ussd-gateway-providers.md`.

---

## pawaPay — verified API contract (research 2026-06-11)
Full findings: `../drc-mvp-research/02-findings/aggregators/pawapay-api-deep-dive.md`
and `.../cross-cutting/operator-detection.md`.

- **Base:** `https://api.sandbox.pawapay.io` / `https://api.pawapay.io`. **Auth:**
  `Authorization: Bearer <token>` (sandbox/prod tokens from the dashboard).
- **Financial:** `POST /v2/deposits` (collect), `POST /v2/payouts` (settle),
  `POST /v2/refunds` (needs the original `depositId`). Each: UUIDv4 op-id + payer/recipient
  `{phoneNumber, provider}` + amount(string) + currency. Idempotent on the op-id. (Note:
  pawaPay's request field is literally `"payer"` even though our customer is the payer.)
- **Operator detection:** `POST /v2/predict-provider` `{phoneNumber}` → `{country,
  provider, phoneNumber(sanitised)}`. High accuracy, **not 100% → allow override.**
- **Dynamic config:** `GET /v2/active-conf` → per-provider status, currencies,
  `decimalsInAmount`, min/max amounts. (Replace our static decimals map with this later.)
- **ASYNC:** financial POSTs return `ACCEPTED/REJECTED/DUPLICATE_IGNORED`; the **final
  outcome arrives via a signed callback (RFC-9421)** → **a callback receiver is
  mandatory** (built — D.1), backed by a **status-polling reconciliation sweep** (D.2).
- **DRC providers:** `VODACOM_MPESA_COD`, `AIRTEL_COD`, `ORANGE_COD`. ⚠️ **Vodacom
  M-Pesa CDF takes NO decimals** (handled in `providers.format_amount`). No Afrimoney.

---

## Merchant pivot — what changed (2026-06-11)
Done in four green passes (A–D):
- **A — Merchant domain:** `domains/merchants/` + `MerchantStore` (memory + SQL) +
  `merchants` table migration + seeded demo merchants.
- **B — Money-core reframe + MDR fee:** renamed payer/payee → customer/merchant
  (orchestrator accounts, `Transaction`, SQL columns + rename migration, schemas, route);
  flipped the fee so the **merchant absorbs the MDR**; transactions now reference a
  `merchant_id`; the route resolves the merchant and server-derives the settlement target.
- **C — USSD channel scaffold:** `ussd/` session state machine + `POST /ussd` + the shared
  `application.start_merchant_payment`; the HTTP route was refactored to call it too (both
  channels now thin callers). Offline-tested end to end.
- **D — Reframe docs/surface:** this DEVLOG, the app `CLAUDE.md`, the web mock, and the research
  `00-overview/product-summary.md`.

Decisions taken (confirmed with the team): **instant pass-through settlement** (keeps
"never hold funds"); **merchant absorbs the fee (MDR)**; keep the *core* ledger/state
machine generic so a later consumer version can reuse it. Recorded as ADRs **0004**
(merchant-acquiring + instant settlement), **0005** (merchant absorbs the MDR), **0006**
(USSD/QR primary customer channel) in `docs/adr/`.

**Follow-on — customer-initiated QR/USSD (2026-06-11).** The USSD handler was refactored to
parse the aggregator's **full accumulated text** (no server-side session), which yields the
**dial-through fast-path** (`*123*1001*10#` → straight to Confirm). Merchants now expose a
dialable `ussd_string` and a **printable QR** of a `tel:` dial-through (`GET /merchants*`,
`/qr.svg` via `segno`). A merchant sticker = QR + the dialable till; the customer scans
(Android) or dials it manually (iOS / feature phones). Merchant-initiated charge-by-number
kept as a fallback (per the team). New dep: `segno`. New config: `DRCPAY_USSD_SHORTCODE`
(placeholder `*123#`). QR-vs-internet design + the "rent the bearer" verdict are in the
research (`ussd-gateway-providers.md`).

---

## Roadmap / what's next
- **pawaPay A–C** ✅ done (outbound client → predict+decimals → wired into orchestrator).
- **USSD channel** ✅ done — full-text parse + **QR/dial-through fast-path**; per-merchant
  payment codes + a printable QR (`segno`); customer-initiated pull is primary,
  charge-by-number the fallback. **Next here:** integrate a **real USSD aggregator** (wire
  format + shortcode provisioning + MNO PIN auth) — a **team action**; the USSD-provider
  research is recorded (`../drc-mvp-research/02-findings/cross-cutting/ussd-gateway-providers.md`).
- **Merchant onboarding** — not started (today merchants are seeded). Needed for real
  launch: create/manage merchants, settlement details, KYC (flag).
- **Phase D.1 — pawaPay callback receiver** ✅ done. `POST /webhooks/pawapay` verifies the
  RFC-9421 signature, correlates by op-id, and drives `on_*_result` idempotently; the
  synchronous REJECT is mapped to an immediate leg failure. Offline-tested; the callback JSON
  shape is provisional (Phase E confirms it).
- **Phase D.2 — reconciliation** ✅ done. `jobs/reconciliation/sweep.py` finds *pending*
  transactions and polls pawaPay's deposit/payout/refund **status endpoints** (new client GET
  methods) to heal missed callbacks, applying any terminal outcome through the shared
  `apply_outcome`. Offline-tested. **Not yet scheduled** — exposing it (an authenticated admin
  trigger, or a cron/worker calling `run_reconciliation` with the container's pieces) is a
  flagged **ops task**, alongside an age/grace-period filter (needs a per-tx timestamp, see TODOs).
- **Phase E — live sandbox** ✅ **connected; full loop verified (2026-06-12).** Sandbox account is
  live; the token sits in `services/api/.env` (git-ignored, the human's secret). A real
  cross-network payment ran end-to-end on `api.sandbox.pawapay.io`: **Vodacom deposit → Airtel
  payout → fee booked**, driven by the **reconciliation sweep polling real status** (no callbacks /
  tunnel needed). Remaining for full Phase E: the **signed-callback** path (needs a public tunnel)
  and a **payout/refund failure** pass. Details in **"Phase E findings"** below.

---

## Phase E findings (live sandbox — verified 2026-06-12)
- **Connected:** sandbox token authenticates (`GET /v2/active-conf` → 200). The app flips to the
  live `PawaPayRail` automatically once `DRCPAY_PAWAPAY_BASE_URL` + `_API_TOKEN` are set.
- **Full collect→settle→reconcile loop verified live** (no callbacks — polling): a Vodacom deposit
  and an Airtel payout both reached `COMPLETED`; ledger balanced (merchant 9.90, revenue 0.10).
- **Status endpoint CONFIRMED:** `GET /v2/{deposits,payouts,refunds}/{id}` →
  `{"data":{…,"depositId"/"status"/"amount"/…},"status":"FOUND"}`. Our provisional `client._status`
  already parses it (unwraps `data`). The Phase D.2 status-shape flag is **resolved**.
- **DRC sandbox test numbers** (success = ends `789`): Vodacom `243813456789`, Airtel `243973456789`,
  Orange `243893456789`. Failures by suffix — deposits `…019/029/039/049/069`, payouts `…089/119`
  (RECIPIENT_NOT_FOUND / UNSPECIFIED_FAILURE). Source: docs.pawapay.io/v2/docs/test_numbers.
- **DRC `active-conf` (sandbox):** all three providers OPERATIONAL; **USD = TWO_PLACES** everywhere
  (so our USD demo amounts are valid); **Vodacom CDF = NONE decimals** (matches research). USD min:
  Vodacom 0.5 / Airtel 0.1 / Orange 0.01; max 2500.
- **Changes made for sandbox:** demo merchants reseeded to sandbox **payout-success** numbers
  (`243973456789` / `243893456789`); reconcile gate broadened to `Container.demo_controls_enabled`
  (simulator **or** sandbox; **blocked in production**), so the console's "Run reconciliation now"
  works against live sandbox; **`tests/conftest.py`** neutralises the local `.env` so the suite
  stays offline/deterministic. Observed: pawaPay set a default `customerMessage` ("docpay") we
  didn't send — account default, harmless.

---

## Open items / TODOs (not blocking, but known)
- **Settlement model:** instant pass-through chosen for MVP; **batched settlement** (hold
  intraday, settle on a schedule / to a bank) is a flagged future option with float +
  licensing implications.
- `merchant_id` on `transactions` is a plain column (no DB FK to `merchants` yet) — enforce
  later. Postgres `merchants` start empty (seed via a script/dashboard); the in-memory demo
  seeds two.
- USSD flow is single-currency (USD), parses the aggregator's full `*`-joined text
  (dial-through fast-path), and has no PIN step (MNO handles auth) — revisit with the real
  aggregator. iOS blocks scan-to-USSD; those + feature phones dial the printed till manually.
- pawaPay **callback** handling: the **callback JSON body shape is STILL provisional** (signature
  *scheme* verified; *fields* not — we drove the live loop by **polling**, not callbacks, so this
  stays open until we wire a public tunnel). The status endpoint's confirmed `data`-wrapped shape is
  a strong hint for the callback shape. The signature's `@authority` comes from the `Host` header,
  so behind a tunnel/proxy it must equal the callback URL pawaPay signed.
- Reconciliation (Phase D.2): the **status-endpoint path + shape are now CONFIRMED** (Phase E,
  2026-06-12) — `GET /v2/{deposits,payouts,refunds}/{id}` → `{"data":{…,"status":…},"status":"FOUND"}`,
  and `client._status` already parses it (unwraps `data`, fails safe on an unreadable status). The sweep currently
  **polls *all* pending transactions** (no age/grace filter — correctness comes from the idempotent
  state-guard, not age); a grace period needs a **per-tx timestamp** on the domain `Transaction`
  (the SQL row already has `updated_at`; the dataclass + in-memory store don't). It is **not yet
  scheduled** (flagged ops task above), and a persistent auth error (401) would surface as
  "unresolved" rather than loudly — add status-code handling when wiring the live sweep (Phase E).
- Idempotency: graceful **concurrent-race** handling (catch unique violation → return
  existing) — currently only sequential retries are graceful.
- Ledger **append-only** is by convention; enforce at DB level later.
- Replace the static `_DECIMALS` map with live `active-conf`.
- Not started: **merchant auth** (`domains/auth/` is an empty placeholder), the **mobile
  app**, the **web dashboard** proper.
- **Legal/licensing (BCC)** — standing flag, not yet investigated.

---

## How to run
```bash
# from services/api, with the venv active
cd services/api && source .venv/bin/activate

# checks
ruff check . && mypy src && pytest

# API (in-memory; zero setup) — seeds demo merchants m_alpha / m_beta
uvicorn --app-dir src drc_pay_api.main:app --reload        # IMPORTANT: --app-dir src

# example: a customer pays Alpha Gas Station (HTTP)
#   curl -X POST localhost:8000/transactions -H 'content-type: application/json' \
#     -d '{"customer_msisdn":"243800000001","merchant_id":"m_alpha","amount":"10.00"}'
# example: USSD dial-through *123*1001*10# (QR scan or manual dial) — text arrives pre-filled
#   curl -X POST localhost:8000/ussd -H 'content-type: application/json' \
#     -d '{"session_id":"s1","msisdn":"243800000001","text":"1001*10"}'    # -> CON Confirm?
#   curl -X POST localhost:8000/ussd -H 'content-type: application/json' \
#     -d '{"session_id":"s1","msisdn":"243800000001","text":"1001*10*1"}'  # -> END initiated
# example: a merchant's payment codes + printable QR
#   curl localhost:8000/merchants/m_alpha          # ussd_string, tel_uri, qr_svg_path
#   curl localhost:8000/merchants/m_alpha/qr.svg   # printable QR (image/svg+xml)

# API on Postgres
docker compose up -d                                        # from repo root
export DRCPAY_DATABASE_URL=postgresql+psycopg://drcpay:drcpay@localhost:5432/drcpay
alembic upgrade head                                        # apply migrations
uvicorn --app-dir src drc_pay_api.main:app --reload

# web Merchant Console — the dev tracker (second terminal). Open http://localhost:5501
python3 -m http.server 5501 --directory "<repo>/tooling/merchant-console"
#   In the console: pick "Await confirmation" → Take payment (lands pending), then
#   "Run reconciliation now" to watch the safety net heal it; click any payment for its ledger.
#   (The console talks to the API at 127.0.0.1:8000; override with ?api=… in the URL.)

# view the DB: TablePlus → host 127.0.0.1, port 5432, user/pass/db = drcpay
```
Note: `create_app()` mounts the demo-only `/demo/reconcile` route **only on the simulator**
(no pawaPay credentials set); a live-rail deployment never exposes it.
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
1. **The money core is role-agnostic** — the consumer→merchant pivot reused the ledger,
   state machine, and orchestrator wholesale; only vocabulary, fee placement, and a
   Merchant entity changed.
2. **Every channel is a thin caller** — HTTP and USSD both call
   `application.start_merchant_payment`; money logic is written once.
3. **USSD is the primary retail channel** — customer-initiated: scan the merchant's QR or
   dial the till (`*123*1001#`). The QR carries a `tel:` USSD dial-through (offline on
   Android; iOS/feature phones dial manually). Renting an aggregator is the outstanding
   channel work (research says rent, don't self-host).
4. **pawaPay is asynchronous** — both halves are now built: the signed **callback receiver**
   (push, D.1) and the **reconciliation sweep** (poll, D.2) for callbacks that never arrive.
   Both funnel through the one `apply_outcome`, so a leg resolves identically either way.
5. **Vodacom M-Pesa CDF = no decimals** — amount formatting must stay provider-aware.
6. **Tests catch real bugs** — the ledger and state machine carry the highest coverage;
   keep writing them first.
7. The skeptic's check we keep applying: invest quality in the **money core**, keep
   everything else minimal; flag honest gaps rather than gold-plate.
