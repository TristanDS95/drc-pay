"""A built-in simulator standing in for an operator's on-net C2B rail during local dev and tests.

It implements the domain ``DirectCollectRail`` shape — the on-net counterpart to the pawaPay
``SimulatedPaymentRail``. A direct collection is only *accepted* synchronously (it records the
request and returns a deterministic op-id); the final outcome is observed **later**, pushed via
``OnNetOrchestrator.on_confirm`` — exactly how a real operator drives it via its confirmation
callback. This keeps the whole on-net flow (router → on-net orchestrator → single ledger posting →
confirm) exercisable offline, with zero network.

Unlike the pawaPay simulator it is *not* also a status poller: the on-net flow has no
reconciliation sweep yet (a flagged gap), so there is nothing to poll.
"""
from __future__ import annotations

from ..domains.ledger.money import Money


class SimulatedDirectRail:
    def __init__(self) -> None:
        # (transaction_id, payer_msisdn, merchant_msisdn, amount, provider) — recorded so tests can
        # assert the operator was asked to move the money straight to the merchant in one leg.
        self.collections: list[tuple[str, str, str, Money, str]] = []

    def request_direct_collection(
        self,
        *,
        transaction_id: str,
        payer_msisdn: str,
        merchant_msisdn: str,
        amount: Money,
        provider: str,
    ) -> str | None:
        self.collections.append((transaction_id, payer_msisdn, merchant_msisdn, amount, provider))
        # A deterministic op-id (``sim-onnet-<tx>``) the orchestrator persists, so a later
        # confirmation callback can correlate back to this transaction via ``find_by_op_id``.
        return f"sim-onnet-{transaction_id}"
