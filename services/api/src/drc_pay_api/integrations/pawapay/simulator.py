"""A built-in simulator standing in for pawaPay during local dev and tests.

It implements the domain ``PaymentRail`` shape: it records each collection / payout /
refund request but does NOT complete them itself. Outcomes are delivered separately by
the caller via the orchestrator's ``on_*_result`` handlers — exactly how pawaPay's
webhooks will drive them in production. This keeps the async, two-phase reality of a
real payment visible, with zero network.
"""
from __future__ import annotations

from ...domains.ledger.money import Money


class SimulatedPaymentRail:
    def __init__(self) -> None:
        self.collections: list[tuple[str, str, Money]] = []
        self.payouts: list[tuple[str, str, Money]] = []
        self.refunds: list[str] = []

    def request_collection(self, *, transfer_id: str, msisdn: str, amount: Money) -> None:
        self.collections.append((transfer_id, msisdn, amount))

    def request_payout(self, *, transfer_id: str, msisdn: str, amount: Money) -> None:
        self.payouts.append((transfer_id, msisdn, amount))

    def request_refund(self, *, transfer_id: str) -> None:
        self.refunds.append(transfer_id)
