"""PawaPayRail — the production payment rail, adapting ``PawaPayClient`` to the domain
``PaymentRail`` port.

For each leg it generates a UUIDv4 operation id (pawaPay is idempotent on these ids and
echoes them back), issues the outbound call, and returns the id so the orchestrator can
persist it for callback correlation and refunds. pawaPay is **asynchronous**: a value
returned here means only that pawaPay *accepted* the request — the final outcome arrives
later via a signed callback (handled by the receiver in ``http/webhook_routes.py``).

A synchronous, non-``ACCEPTED`` ack raises ``PawaPayRailError`` (a domain ``RailRejected``);
the orchestrator maps that to an immediate failure of the leg. The async *callbacks* are
handled by the signed-callback receiver (``http/webhook_routes.py``).
"""
from __future__ import annotations

import uuid

from ...domains.ledger.money import Money
from ...domains.transactions.ports import RailRejected
from .client import PawaPayAck, PawaPayClient


class PawaPayRailError(RailRejected):
    """pawaPay did not accept a financial request synchronously."""

    def __init__(self, message: str, *, ack: PawaPayAck | None = None) -> None:
        super().__init__(message)
        self.ack = ack


def _ensure_accepted(operation: str, ack: PawaPayAck) -> None:
    if not ack.accepted:
        detail = ack.failure_message or ack.failure_code or ack.status
        raise PawaPayRailError(f"pawaPay {operation} not accepted: {detail}", ack=ack)


class PawaPayRail:
    """Implements ``PaymentRail`` by wrapping the pawaPay v2 client."""

    def __init__(self, client: PawaPayClient) -> None:
        self._client = client

    def request_collection(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        deposit_id = str(uuid.uuid4())
        ack = self._client.request_deposit(
            deposit_id=deposit_id, phone_number=msisdn, provider=provider, amount=amount
        )
        _ensure_accepted("deposit", ack)
        return deposit_id

    def request_payout(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        payout_id = str(uuid.uuid4())
        ack = self._client.request_payout(
            payout_id=payout_id, phone_number=msisdn, provider=provider, amount=amount
        )
        _ensure_accepted("payout", ack)
        return payout_id

    def request_refund(
        self, *, transaction_id: str, deposit_id: str | None, amount: Money, provider: str
    ) -> str | None:
        if deposit_id is None:
            raise PawaPayRailError("cannot refund without the original depositId")
        refund_id = str(uuid.uuid4())
        ack = self._client.request_refund(
            refund_id=refund_id, deposit_id=deposit_id, amount=amount, provider=provider
        )
        _ensure_accepted("refund", ack)
        return refund_id
