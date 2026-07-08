# ADR 0007 - pawaPay's cost is an expense, not revenue

- **Status:** Accepted (2026-06-17). Refines the ledger consequences of ADR 0005.
- **Context:** The orchestrator booked the **entire** merchant fee (MDR) to `revenue:fees` and
  recorded pawaPay's processing cost **nowhere**. Because the MDR currently equals pawaPay's
  pass-through cost (no margin yet - ADR 0005), this overstated revenue and hid that real margin
  is **zero**. Worse, a payout that fails and refunds still incurs pawaPay's collection fee, but
  with no expense account that loss was invisible - the books showed a clean wash.
- **Decision:** Book pawaPay's per-leg cost to a new ledger account **`expense:pawapay`** as each
  leg completes; `revenue:fees` now holds **only the margin** (MDR − cost).
  - The collection fee is booked at collection success (clearing receives the amount net of it,
    matching pawaPay's "fees deducted after collection"); the payout fee at payout success; the
    leftover MDR, if any, is the margin → `revenue:fees`.
  - A refund returns the customer the full amount; the already-booked collection fee stays in
    `expense:pawapay`, so a refunded transaction correctly shows a **negative margin** (a loss).
  - `expense:pawapay` is a **ledger account** (a string), not a new entity and not a transaction
    field. The cost is computed at posting time from the amount + providers already on the
    transaction (`pricing.collection_cost` / `pricing.payout_cost`) - **no migration**.
- **Consequences:**
  - The ledger now answers two questions per transaction that it conflated before: *what did we
    keep?* (`revenue:fees`) and *what did the rails cost?* (`expense:pawapay`). Margin = revenue −
    expense, derivable per network pair.
  - With no margin today, revenue is **exactly 0** and expense carries the full cost - the honest
    "we keep nothing" picture. This is the seam the pricing decision (ADR 0005) plugs into: set
    `mdr = cost + margin` in `pricing.py` and the surplus flows to `revenue:fees` automatically.
  - **Flag (load-bearing):** pawaPay's callback does **not** return the exact fee it charged
    (confirmed in their docs - only `amount` + `status`), so the booked figure is an **estimate**
    from published per-leg rates, to be **reconciled against pawaPay settlement statements**.
  - **Flag (researched 2026-06-17):** pawaPay's Plans page bills refunds like disbursements -
    "1% + MMO fee for Disbursements, Refunds\* & Remittances" (note the unread `*` caveat) - so a refund
    **does** carry a fee (≈ the disbursement rate on the payer's operator). Whether the original
    **collection fee is reversed** on a refund is stated nowhere (assumed sunk; confirm with pawaPay).
    The refund object exposes no fee field, so the figure is an estimate like the others. Our refund path
    currently books **only** the sunk collection fee; wiring the refund-leg expense is a known follow-up.
    See research `fees-and-costs.md`.
- **Alternatives considered:** **Gross presentation** - book the full MDR to revenue plus a
  contra account for the cost - rejected for v1: more accounts and code for the same net margin;
  we chose the **net** view (revenue = margin). A formal **chart-of-accounts / P&L types** -
  deferred; accounts stay bare strings as they are today.
