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
  clean, **89 tests passing**. Built: the payment spine, the **Merchant domain**, the
  **MDR fee model**, Postgres persistence, Alembic migrations, idempotency, the pawaPay
  outbound client **wired into the orchestrator**, a first-class **USSD channel**,
  **customer-initiated QR/USSD payments** (per-merchant payment codes + a printable QR), and
  the **pawaPay callback receiver** (Phase D.1: signed-webhook verify → reconcile into state).
- **Channels:** the **USSD channel** (customer-initiated — the customer scans the
  merchant's QR or dials the till; the **primary** retail flow) and the **HTTP API** (the
  merchant app/dashboard, incl. a merchant-initiated *charge-by-number* push **fallback**)
  are both thin callers into the *same* orchestrator via `application.start_merchant_payment`.
- **Mobile app (`apps/mobile`)**: not started (only `theme/tokens.ts`). A **web
  merchant-app mock** (`tooling/phone-mock`) exists for visual testing (bilingual: the
  merchant's **QR + till**, a payments feed, a customer-USSD-pay simulator, and the
  charge-by-number fallback).
- **Immediate next:** **Phase D.1 (the pawaPay callback receiver) is done** — RFC-9421
  signature verification + correlate-by-op-id + drive `on_*_result` idempotently + the
  synchronous-REJECT fix. Next is **Phase D.2** (the reconciliation sweep for missed
  callbacks), then the **real USSD aggregator** + **merchant onboarding** — and the live
  sandbox test (Phase E, needs credentials), which also confirms the *provisional* callback
  JSON shape.

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
│               webhooks.py      # process_pawapay_callback — verify → correlate → drive
├── adapters/
│   ├── memory.py                # in-memory stores/ledger/recorder (demo + tests)
│   └── sql.py                   # SQLAlchemy 2.0 Postgres stores + ledger
├── integrations/pawapay/
│   ├── client.py                # PawaPayClient (deposits/payouts/refunds/predict)
│   ├── providers.py             # DRC codes + provider_decimals/format_amount
│   ├── rail.py                  # PawaPayRail — client → PaymentRail port
│   ├── signatures.py            # verify RFC-9421 / ECDSA-P256 callback signatures
│   ├── callbacks.py             # parse a callback → CallbackEvent (provisional shape)
│   └── simulator.py             # SimulatedPaymentRail (the demo rail)
├── ussd/  session.py            # USSD channel: full-text parse + QR/dial fast-path → orchestrator
├── http/  routes.py schemas.py container.py ussd_routes.py merchant_routes.py webhook_routes.py
├── jobs/reconciliation/         # EMPTY — Phase D.2 (poll status for stuck/missed callbacks)
├── main.py                      # create_app() factory; module-level `app`
└── config.py                    # 12-factor settings (DRCPAY_* env vars)
migrations/                      # Alembic (5: baseline → idempotency → pawaPay ids →
                                 #   merchants table → merchant-pivot rename)
tests/                           # 89 tests
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

## Built & verified (ruff + mypy --strict clean, 89 tests)
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
  `DRCPAY_PAWAPAY_PUBLIC_KEY`, correlates by op-id (`find_by_op_id`), and drives `on_*_result`
  **idempotently** (state-guarded against resends). A synchronous rail **REJECT** (`RailRejected`)
  now maps to an immediate leg failure. Signature scheme verified offline (self-generated key);
  the callback **JSON body shape is provisional** (confirm in Phase E). New dep: `cryptography`.
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
- **Web merchant-app mock** (`tooling/phone-mock`): EN/FR — the merchant's **QR + till**, a
  live payments feed, a customer-USSD-pay simulator, and the charge-by-number fallback;
  live ops console.

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
  mandatory** (Phase D, currently paused).
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
- **D — Reframe docs/surface:** this DEVLOG, the app `CLAUDE.md`, the phone-mock (now a
  merchant "take payment" app), and the research `00-overview/product-summary.md`.

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
- **Phase D.2 — reconciliation (NEXT).** A `jobs/reconciliation` sweep that finds stuck
  *pending* transactions and polls pawaPay's deposit/payout/refund **status endpoints** (new
  client GET methods) to resolve missed callbacks.
- **Phase E — live sandbox test:** **TEAM ACTION** — sign up at
  `dashboard.sandbox.pawapay.io`, set `DRCPAY_PAWAPAY_BASE_URL` + `DRCPAY_PAWAPAY_API_TOKEN`,
  then exercise the real flow. (We don't sign up.)

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
- pawaPay callback handling: the **callback JSON body shape is provisional** (the signature
  *scheme* is verified; the *fields* are not) — confirm against real sandbox callbacks in
  Phase E. The signature's `@authority` is taken from the `Host` header, so behind a proxy it
  must equal the callback URL pawaPay signed.
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

# web merchant-app mock (second terminal)
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
1. **The money core is role-agnostic** — the consumer→merchant pivot reused the ledger,
   state machine, and orchestrator wholesale; only vocabulary, fee placement, and a
   Merchant entity changed.
2. **Every channel is a thin caller** — HTTP and USSD both call
   `application.start_merchant_payment`; money logic is written once.
3. **USSD is the primary retail channel** — customer-initiated: scan the merchant's QR or
   dial the till (`*123*1001#`). The QR carries a `tel:` USSD dial-through (offline on
   Android; iOS/feature phones dial manually). Renting an aggregator is the outstanding
   channel work (research says rent, don't self-host).
4. **pawaPay is asynchronous** — the callback receiver (Phase D, paused) is mandatory, not
   optional, before going live.
5. **Vodacom M-Pesa CDF = no decimals** — amount formatting must stay provider-aware.
6. **Tests catch real bugs** — the ledger and state machine carry the highest coverage;
   keep writing them first.
7. The skeptic's check we keep applying: invest quality in the **money core**, keep
   everything else minimal; flag honest gaps rather than gold-plate.
