# ADR 0003 — Pass-through model, no fund custody (v1)

- **Status:** Accepted (2026-06-09)
- **Context:** Holding customer balances triggers e-money / payment-institution
  licensing. The feasibility research recommends renting rails (pawaPay) and moving
  money straight through.
- **Decision:** v1 is a **pure pass-through**: funds flow payer-wallet → pawaPay →
  payee-wallet. The app **never holds a balance**. Each transfer is collect-then-payout
  with an automatic refund if the payout fails after collection succeeded.
- **Consequences:**
  - Keeps us out of custody / e-money licensing for v1 (legal posture remains a flag
    to investigate with the BCC — Banque Centrale du Congo).
  - Forgoes float / cash-out / agent revenue; monetisation = transfer fee + CDF↔USD FX
    spread now, lending and merchant layers later (per the comparables synthesis).
  - The ledger records **movement, not stored value**.
- **Alternatives considered:** wallet / stored-value — rejected for v1: licensing,
  capital requirements, and a much larger fraud surface.
