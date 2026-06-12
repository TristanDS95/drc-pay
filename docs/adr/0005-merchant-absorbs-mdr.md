# ADR 0005 — Fee model: the merchant absorbs the MDR

- **Status:** Accepted (2026-06-11). Replaces the earlier consumer "fee added on top of the
  payer's debit" model.
- **Context:** In merchant acquiring the customer pays the **sticker price** and the merchant
  bears the **merchant discount rate (MDR)** — the same shape as card/MM acquiring. Our earlier
  consumer framing charged the payer `amount + fee`, which is unusual for in-person retail and
  visible to the customer at the till.
- **Decision:** The **customer pays exactly `amount`**; the **merchant nets `amount − fee`**;
  we book `fee` to `revenue:fees` **only on a successful settlement**. The fee is the MDR. In
  code, `pricing.py` is a **1% placeholder** and the orchestrator requires `fee < amount`.
- **Consequences:**
  - Ledger (verified in tests): collect = `customer` debit `amount` · `clearing` credit
    `amount`; settle = `clearing` debit `amount` · `merchant` credit `amount − fee` · `revenue`
    credit `fee`; refund returns the **full `amount`** to the customer (no fee on failure).
  - **Open pricing risk (load-bearing):** pawaPay's round-trip cost is **~3.5–5%**, so the **1%
    placeholder is below cost** — at it we lose money per transaction. The real MDR must cover
    all-in cost + margin (≈**5–7%+**); it is **not yet set**. Flat per-session USSD cost
    (~$0.034) makes small tickets worse (regressive). See
    `../../../drc-mvp-research/02-findings/cross-cutting/fees-and-costs.md` +
    `ussd-gateway-providers.md`.
- **Alternatives considered:** customer-pays-fee-on-top (the old consumer model) — rejected for
  retail. Per-merchant configurable MDR — likely later; the placeholder is a single global rate
  for now.
