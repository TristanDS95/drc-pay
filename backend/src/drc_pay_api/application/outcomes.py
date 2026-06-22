"""Apply a resolved leg outcome to a transaction — the single code path shared by the
webhook receiver (a *pushed* callback) and the reconciliation sweep (a *polled* status).

Whichever way pawaPay's final word reaches us, it lands here, so a leg resolves identically
push or poll — there is exactly one place that turns "this leg succeeded/failed" into a state
transition + ledger posting. The apply is state-guarded: an outcome for a leg the transaction
has already moved past is ignored, which makes both callers idempotent against resends/races.
"""
from __future__ import annotations

from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.ports import LedgerPort, PaymentRail, TransactionStore
from ..domains.transactions.state_machine import TxState

# The state a transaction must be in for a given leg's outcome to apply. An outcome that
# arrives when the transaction is NOT in this state is a duplicate / out-of-order resend.
# (Its values are exactly ``state_machine.PENDING_STATES`` — asserted in the tests.)
AWAITING_STATE: dict[str, TxState] = {
    "deposit": TxState.COLLECTION_PENDING,
    "payout": TxState.PAYOUT_PENDING,
    "refund": TxState.REFUND_PENDING,
}


def apply_outcome(
    *,
    store: TransactionStore,
    rail: PaymentRail,
    ledger: LedgerPort,
    transaction_id: str,
    kind: str,
    success: bool,
) -> str:
    """Drive the orchestrator's ``on_*_result`` for ``kind`` (deposit / payout / refund),
    guarded by the transaction's current state. Returns ``"applied"`` if the outcome moved
    the transaction, or ``"ignored: already applied (state=…)"`` if the guard tripped (the
    leg was already resolved — a resent callback, or a callback that beat the sweep)."""
    transaction = store.get(transaction_id)
    if transaction.state is not AWAITING_STATE[kind]:
        return f"ignored: already applied (state={transaction.state.value})"
    orchestrator = Orchestrator(store, rail, ledger)
    if kind == "deposit":
        orchestrator.on_collection_result(transaction_id, success=success)
    elif kind == "payout":
        orchestrator.on_payout_result(transaction_id, success=success)
    else:
        orchestrator.on_refund_result(transaction_id, success=success)
    return "applied"
