"""Test doubles for the orchestrator.

The in-memory store and ledger are the real adapters from ``drc_pay_api.adapters``
(no need to duplicate them here). This module only provides ``FakePaymentRail``, which
records requests so a test can assert on them, then deliver outcomes via the
orchestrator's ``on_*_result`` handlers.
"""
from __future__ import annotations

from drc_pay_api.domains.ledger.money import Money


class FakePaymentRail:
    def __init__(self) -> None:
        self.collections: list[tuple[str, str, Money]] = []
        self.payouts: list[tuple[str, str, Money]] = []
        self.refunds: list[str] = []

    def request_collection(self, *, transaction_id: str, msisdn: str, amount: Money) -> None:
        self.collections.append((transaction_id, msisdn, amount))

    def request_payout(self, *, transaction_id: str, msisdn: str, amount: Money) -> None:
        self.payouts.append((transaction_id, msisdn, amount))

    def request_refund(self, *, transaction_id: str) -> None:
        self.refunds.append(transaction_id)
