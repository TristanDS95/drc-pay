# Future development — longer-horizon work

The **near-term** roadmap lives in [`DEVLOG.md`](./DEVLOG.md) ("NEXT — biggest open rocks").
This file holds the **longer-horizon / someday** items: things that are real plans but not the
current build. It consolidates notes that used to live as placeholder `README`s in empty folders
(`apps/`, `infra/`, `services/webhooks/`, `tooling/pawapay-sim/`) — removed in the repo restructure
(ADR 0008) so the tree reflects what actually exists today (a Python backend + static web front-ends).

---

## Mobile app (smartphone, native)

**React Native + Expo** — one codebase, iOS + Android. Not yet initialized. Deliberately deferred:
the product is **web-first** for now (the Merchant Console + the customer scan-to-pay page cover the
MVP).

When we scaffold it (`npx create-expo-app@latest .`), adopt a **feature-first** structure:

```
src/
├── features/    # send, history, auth, profile — screens + hooks per feature
├── components/  # shared dumb UI (Button, AmountInput, PinPad)
├── api/         # client generated from the backend OpenAPI schema
├── lib/         # money formatting, MSISDN parse/validate, i18n (fr/)
└── theme/       # design tokens — see docs/design-tokens.md
```

- **Design:** mirrors `../../drc-mvp-research/05-product-spec/ui-spec.md` — Wave-style minimal, coral
  accent, Inter, flat 12px-rounded components (no shadows), 3-tab nav (Envoyer / Historique / Profil),
  French in v1. The palette/scale are captured in [`design-tokens.md`](./design-tokens.md) so the spec
  and the code can't drift.
- **Release:** via **EAS** with a **force-update** path — in a payments app you must be able to kill a
  broken client version fast. Staged rollout; never 100% of users at once.
- **CI:** add a mobile job (lint + type-check + EAS build) to `.github/workflows/ci.yml` once it exists.

## Admin / operations dashboard

Internal support/ops console — **later, not in v1.** When built: look up a transaction, see its
ledger entries and state-machine history, action a `manual_review` item, watch operator health.
Internal-only, **behind SSO**, with strong **audit logging** on every action. Likely a small
React/Next app talking to a **separate, privileged admin API surface** (never the consumer API).

## Production infrastructure (AWS)

Infrastructure-as-code (**Terraform**) for AWS **Cape Town (af-south-1)** — the eventual production
home (the sandbox runs on Railway as a single container today). To provision: VPC, **ECS Fargate**
services (App Runner isn't available in af-south-1), **RDS Postgres** (the ledger), **ElastiCache
Redis** (sessions / rate limits), **Secrets Manager**, an **ALB**, and **CloudWatch**.

**Rules:**
- Separate **sandbox** and **production** accounts / workspaces; never share creds.
- No secrets in committed state (remote state + git-ignored `*.tfvars`).
- Least-privilege IAM per service.

## Security hardening (pre-production / when auth exists)

The full staged checklist now lives in **[`security-roadmap.md`](./security-roadmap.md)** - the single
source of truth for what is done, what gates the first real-money pilot (Gate A: merchant auth +
per-merchant authorization, USSD/aggregator hardening, rate limits, CORS, charge expiry, audit
logging), and what gates production at scale (Gate B: PII field encryption, Argon2id PINs if own auth
is built, monitoring, KYC, backups). Tick items there, not here.

## Webhook receiver as its own deployable

Today the pawaPay webhook receiver lives **inside the backend** (`http/webhook_routes.py` +
`application/webhooks.py`, RFC-9421 signature verification) — and that's fine for now. The longer-term
option is to **split it into its own service**, because it has a different profile from the
user-facing API:

- It's a **public endpoint** whose security model is **signature verification** (RFC-9421 public-key,
  ECDSA-P256 — *not* HMAC), and it must stay available so we never lose payment-outcome events — a
  different scaling/hardening profile from the JWT-authenticated API.
- Responsibilities if split out: verify every inbound signature (reject unsigned/stale); translate the
  event into a domain action (advance the state machine via the shared domain layer); be **idempotent**
  (the same event may arrive twice); **dead-letter** anything it can't process for the reconciliation
  job to resolve.

Defer until the availability/scaling case is real; the in-backend receiver + reconciliation sweep
cover the MVP.

## Standalone pawaPay simulator (probably not needed)

A standalone **HTTP fake of pawaPay** (a process that accepts pawaPay-shaped collection/payout/refund
requests and later **fires signed RFC-9421 webhooks** back at us) — considered, **deprioritized.** The
in-process `SimulatedPaymentRail` (`integrations/pawapay/simulator.py`) already covers the unit tests
and the API-level demo with zero network, and we test the real async path against pawaPay's live
sandbox. Only worth building if we split the webhook receiver out (above) and want to exercise the
real missed-webhook → reconciliation path against actual network calls. Until then, don't duplicate the
in-process simulator's logic.

---

## On-net (same-network) — facilitate & record

Direction set by [ADR 0009](adr/0009-on-net-facilitate-and-record.md): for same-network payments we do
**not** route or hold money — the customer pays the merchant **directly on the operator's own rail** and
we **record & confirm** (non-custodial, `fee=0`). The earlier operator-API "direct-collect" approach is
**retired** (Airtel's Collection API has no payee field → it would make us the merchant → custody → EMI
licence). Active status + the next build step (trim the rail machinery) live in `DEVLOG.md` (NEXT).

**Longer-horizon enhancement:** **auto-confirmation** via the operator's merchant-payment notification (a
till that pings us when paid), removing the merchant's manual "Confirm received" tap — to confirm per
operator. Research context:
`../../drc-mvp-research/02-findings/cross-cutting/{on-net-direct-operator-apis,own-aggregator}.md`.
