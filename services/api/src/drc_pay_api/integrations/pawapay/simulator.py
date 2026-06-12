"""A built-in simulator standing in for pawaPay during local dev and tests.

It implements the domain ``PaymentRail`` **and** the ``StatusPoller`` shape, so it models
pawaPay's two realities faithfully:

  - a financial request is only *accepted* synchronously — it returns an op-id, never a
    final outcome;
  - that outcome is observed **later**, either *pushed* via the orchestrator's
    ``on_*_result`` handlers (the webhook path) or *pulled* by polling ``get_*_status``
    (the reconciliation path) — exactly how the real pawaPay drives them in production.

In the demo every accepted operation is recorded as ``COMPLETED`` on pawaPay's side. Whether
OUR transaction has heard about it yet is a *separate* matter — and that gap is precisely
what lets the reconciliation sweep be demonstrated offline: start a payment, hold its
callback (``defer``), then watch a status poll heal it. All with zero network.
"""
from __future__ import annotations

from ...domains.ledger.money import Money
from .status import PawaPayStatus


class SimulatedPaymentRail:
    def __init__(self) -> None:
        self.collections: list[tuple[str, str, Money, str]] = []
        self.payouts: list[tuple[str, str, Money, str]] = []
        self.refunds: list[tuple[str, str | None, Money]] = []
        # op-id → pawaPay status. Deterministic ids (``sim-<leg>-<tx>``) keep tests legible.
        self._status: dict[str, str] = {}

    def request_collection(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.collections.append((transaction_id, msisdn, amount, provider))
        return self._accept(f"sim-dep-{transaction_id}")

    def request_payout(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.payouts.append((transaction_id, msisdn, amount, provider))
        return self._accept(f"sim-pay-{transaction_id}")

    def request_refund(
        self, *, transaction_id: str, deposit_id: str | None, amount: Money, provider: str
    ) -> str | None:
        self.refunds.append((transaction_id, deposit_id, amount))
        return self._accept(f"sim-ref-{transaction_id}")

    def _accept(self, op_id: str) -> str:
        # pawaPay accepts the request and (in the demo) completes it on its side. The outcome
        # still reaches us only via a callback or a status poll — never synchronously here.
        self._status[op_id] = "COMPLETED"
        return op_id

    # ---- StatusPoller — the reconciliation sweep polls these ----------
    def get_deposit_status(self, deposit_id: str) -> PawaPayStatus:
        return PawaPayStatus(self._status.get(deposit_id))

    def get_payout_status(self, payout_id: str) -> PawaPayStatus:
        return PawaPayStatus(self._status.get(payout_id))

    def get_refund_status(self, refund_id: str) -> PawaPayStatus:
        return PawaPayStatus(self._status.get(refund_id))
