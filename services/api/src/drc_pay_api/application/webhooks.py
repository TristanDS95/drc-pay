"""Application service: process an inbound pawaPay callback — verify it, correlate it to a
transaction by op-id, and drive the orchestrator's ``on_*_result`` idempotently.

A thin caller (the ``/webhooks/pawapay`` HTTP route) hands the raw request in; this owns
the verify → parse → correlate → drive flow, channel-agnostic and offline-testable.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from ..domains.transactions.models import Transaction
from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.ports import LedgerPort, PaymentRail
from ..domains.transactions.state_machine import TxState
from ..integrations.pawapay.callbacks import parse_callback
from ..integrations.pawapay.signatures import verify_pawapay_signature

# The state a transaction must be in for a given leg's callback to apply. A callback that
# arrives when the transaction is NOT in this state is a duplicate or out-of-order resend
# → ignored, which makes the receiver idempotent (pawaPay can and does resend callbacks).
_AWAITING = {
    "deposit": TxState.COLLECTION_PENDING,
    "payout": TxState.PAYOUT_PENDING,
    "refund": TxState.REFUND_PENDING,
}


class WebhookStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...

    def find_by_op_id(self, op_id: str) -> Transaction | None: ...


def process_pawapay_callback(
    *,
    store: WebhookStore,
    rail: PaymentRail,
    ledger: LedgerPort,
    public_key_pem: str,
    method: str,
    path: str,
    host: str,
    headers: Mapping[str, str],
    raw_body: bytes,
    now: int,
) -> str:
    """Verify + apply a callback. Raises ``SignatureError`` if the signature is bad (the
    caller maps that to 401). Returns a short status describing what was done."""
    verify_pawapay_signature(
        public_key_pem=public_key_pem,
        method=method,
        path=path,
        host=host,
        headers=headers,
        raw_body=raw_body,
        now=now,
    )
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return "ignored: body is not JSON"
    if not isinstance(body, dict):
        return "ignored: body is not an object"

    event = parse_callback(body)
    if event is None:
        return "ignored: non-terminal or unrecognised callback"

    transaction = store.find_by_op_id(event.op_id)
    if transaction is None:
        return "unmatched: no transaction for that op-id"
    if transaction.state is not _AWAITING[event.kind]:
        return f"ignored: already applied (state={transaction.state.value})"

    orchestrator = Orchestrator(store, rail, ledger)
    if event.kind == "deposit":
        orchestrator.on_collection_result(transaction.id, success=event.success)
    elif event.kind == "payout":
        orchestrator.on_payout_result(transaction.id, success=event.success)
    else:
        orchestrator.on_refund_result(transaction.id, success=event.success)
    return "applied"
