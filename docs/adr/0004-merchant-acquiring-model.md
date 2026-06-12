# ADR 0004 — Merchant-acquiring model (was: consumer pay-any-number)

- **Status:** Accepted (2026-06-11). Reframes the consumer product assumed by ADRs 0001–0003
  and the early `05-product-spec`; those technical decisions still hold.
- **Context:** We began as a *consumer* app to pay any mobile-money number across networks.
  After a team review — with **~40 gas stations + pop-up stores already lined up** (merchant
  acquisition, usually the hardest part of a new acquiring product, is substantially
  de-risked) — we pivoted to a **merchant-acquiring** product: merchants accept cross-network
  mobile-money payments; **consumers do not need the app**. The money core (double-entry
  ledger, state machine, orchestrator) was role-agnostic, so the pivot reused it wholesale.
- **Decision:** The MVP is **merchant-facing**. A customer pays a **registered merchant**; we
  collect from the customer and **settle instantly, per transaction**, to the merchant's
  mobile-money account — a **pure pass-through** (extends ADR 0003; we still never hold a
  balance). **Merchant onboarding is in scope** (identity, settlement account, till/short-code;
  business KYC flagged). The generic ledger/state machine stays role-agnostic so a *consumer*
  version could reuse it much later.
- **Consequences:**
  - Adds a `domains/merchants` entity + a `merchant_id` on each transaction; the route/USSD
    server-derives the merchant's settlement target (never trust the client).
  - Instant per-transaction settlement keeps us out of fund custody (ADR 0003 intact). Batched
    settlement (holding intraday) was considered and **deferred** — it reintroduces float +
    licensing exposure.
  - The product surface (app, dashboard, demo) is merchant-first; a consumer app is deferred.
- **Alternatives considered:** keep the consumer pay-any-number app — rejected: the merchant
  launch is concretely de-risked, consumer acquisition is harder/costlier, and the merchant
  model captures a clearer, contractible fee (the MDR, ADR 0005).
