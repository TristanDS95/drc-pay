"""pawaPay integration boundary.

The ONLY package that knows pawaPay's wire format. The real HTTP client (``client.py``)
implements the domain ``PaymentRail`` port
(``drc_pay_api.domains.transactions.ports.PaymentRail``) via ``rail.py``, so the
orchestrator never depends on pawaPay's request/response shapes. For local dev and tests,
the in-process ``simulator.SimulatedPaymentRail`` plays that role. Amounts cross this
boundary as integer minor units + currency, matching ``domains.ledger.money.Money``.
"""
