"""pawaPay integration boundary.

The ONLY package that knows pawaPay's wire format. The real HTTP client will live here
and implement the domain ``PaymentRail`` port
(``drc_pay_api.domains.transactions.ports.PaymentRail``), so the orchestrator never
depends on pawaPay's request/response shapes. For local dev and tests, the in-process
``simulator.SimulatedPaymentRail`` plays that role.

Nothing to import yet — the real client is added once pawaPay sandbox access is in
hand. Amounts cross this boundary as integer minor units + currency, matching
``domains.ledger.money.Money``.
"""
