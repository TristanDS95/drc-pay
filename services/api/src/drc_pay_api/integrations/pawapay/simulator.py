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
        self.collections: list[tuple[str, str, Money, str]] = []
        self.payouts: list[tuple[str, str, Money, str]] = []
        self.refunds: list[tuple[str, str | None, Money]] = []

    def request_collection(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.collections.append((transaction_id, msisdn, amount, provider))
        return None  # the simulator issues no op-id; outcomes arrive via on_*_result

    def request_payout(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.payouts.append((transaction_id, msisdn, amount, provider))
        return None

    def request_refund(
        self, *, transaction_id: str, deposit_id: str | None, amount: Money, provider: str
    ) -> str | None:
        self.refunds.append((transaction_id, deposit_id, amount))
        return None
