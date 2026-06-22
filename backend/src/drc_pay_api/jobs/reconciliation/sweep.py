"""Reconciliation sweep — the missed-callback safety net.

pawaPay delivers a deposit / payout / refund's final outcome via a callback, but callbacks
can be missed (a network blip, downtime, a bad deploy). This sweep is the backstop: it finds
every transaction still awaiting an outcome, polls pawaPay's status endpoint for that leg, and
— on a terminal status — drives the very same ``apply_outcome`` a callback would, so the
transaction self-heals. Anything not yet terminal is left for the next sweep.

It reuses the orchestrator wholesale (via ``apply_outcome``) and is state-guarded, so it is
idempotent and safe to run alongside live callbacks: if a callback resolves a leg first, the
sweep's apply is a no-op. Offline-testable: it depends only on ports + a ``StatusPoller``.

Not yet wired to a schedule — exposing it (an authenticated admin trigger, or a scheduled
worker calling ``run_reconciliation`` with the container's pieces) is a flagged ops task.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ...application.outcomes import AWAITING_STATE, apply_outcome
from ...domains.transactions.models import Transaction
from ...domains.transactions.ports import LedgerPort, PaymentRail
from ...integrations.pawapay.status import Outcome, PawaPayStatus, StatusPoller, classify

# Per-transaction disposition of one sweep pass — what we did (or didn't) with each pending tx.
RESOLVED_SUCCESS = "resolved_success"  # polled terminal SUCCESS → leg advanced
RESOLVED_FAILURE = "resolved_failure"  # polled terminal FAILURE → leg failed (may auto-refund)
STILL_PENDING = "still_pending"  # polled a real, non-terminal status → left for the next sweep
UNRESOLVED = "unresolved"  # status couldn't be read (non-2xx / unexpected shape) → left alone
SKIPPED_NO_OP_ID = "skipped_no_op_id"  # no pawaPay op-id to poll (e.g. a simulator-issued leg)
ALREADY_APPLIED = "already_applied"  # a callback won the race between find_pending and apply
POLL_ERROR = "poll_error"  # the status request itself raised (network / timeout)

# Which leg a pending transaction is awaiting — the inverse of ``AWAITING_STATE``.
_LEG_FOR_STATE = {state: kind for kind, state in AWAITING_STATE.items()}


class ReconciliationStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...

    def find_pending(self) -> list[Transaction]: ...


@dataclass(frozen=True)
class ReconciliationItem:
    transaction_id: str
    kind: str  # deposit | payout | refund
    disposition: str


@dataclass
class ReconciliationSummary:
    """The outcome of one sweep pass — one item per pending transaction examined."""

    items: list[ReconciliationItem] = field(default_factory=list)

    def count(self, disposition: str) -> int:
        return sum(1 for item in self.items if item.disposition == disposition)

    @property
    def resolved(self) -> int:
        """How many transactions this pass actually moved (succeeded or failed)."""
        return self.count(RESOLVED_SUCCESS) + self.count(RESOLVED_FAILURE)

    @property
    def total(self) -> int:
        return len(self.items)


def _op_id(transaction: Transaction, kind: str) -> str | None:
    return {
        "deposit": transaction.deposit_id,
        "payout": transaction.payout_id,
        "refund": transaction.refund_id,
    }[kind]


def _poll(poller: StatusPoller, kind: str, op_id: str) -> PawaPayStatus:
    if kind == "deposit":
        return poller.get_deposit_status(op_id)
    if kind == "payout":
        return poller.get_payout_status(op_id)
    return poller.get_refund_status(op_id)


def reconcile_pending(
    *,
    store: ReconciliationStore,
    rail: PaymentRail,
    ledger: LedgerPort,
    poller: StatusPoller,
) -> ReconciliationSummary:
    """One sweep pass: poll every pending transaction's awaited leg and apply any terminal
    outcome. Never raises on a single bad poll — one failure is recorded as ``POLL_ERROR`` and
    the sweep continues, so the safety net can't be taken down by one stuck operation."""
    summary = ReconciliationSummary()
    for transaction in store.find_pending():
        kind = _LEG_FOR_STATE.get(transaction.state)
        if kind is None:
            continue  # defensive: find_pending only yields the three pending states
        op_id = _op_id(transaction, kind)
        if op_id is None:
            summary.items.append(ReconciliationItem(transaction.id, kind, SKIPPED_NO_OP_ID))
            continue
        try:
            status = _poll(poller, kind, op_id)
        except httpx.HTTPError:
            summary.items.append(ReconciliationItem(transaction.id, kind, POLL_ERROR))
            continue
        disposition = _resolve(store, rail, ledger, transaction.id, kind, status)
        summary.items.append(ReconciliationItem(transaction.id, kind, disposition))
    return summary


def _resolve(
    store: ReconciliationStore,
    rail: PaymentRail,
    ledger: LedgerPort,
    transaction_id: str,
    kind: str,
    status: PawaPayStatus,
) -> str:
    """Turn a polled status into a disposition, applying it through the shared applier when
    it's terminal. ``None`` status / non-terminal status leave the transaction untouched."""
    if status.status is None:
        return UNRESOLVED
    outcome = classify(status.status)
    if outcome is Outcome.PENDING:
        return STILL_PENDING
    result = apply_outcome(
        store=store,
        rail=rail,
        ledger=ledger,
        transaction_id=transaction_id,
        kind=kind,
        success=outcome is Outcome.SUCCESS,
    )
    if result != "applied":
        return ALREADY_APPLIED  # a callback resolved it first — the state guard tripped
    return RESOLVED_SUCCESS if outcome is Outcome.SUCCESS else RESOLVED_FAILURE


def run_reconciliation(
    *,
    store: ReconciliationStore,
    rail: PaymentRail,
    ledger: LedgerPort,
    poller: StatusPoller | None,
) -> ReconciliationSummary:
    """Composition-friendly entry point: run a sweep from a container's pieces, tolerating a
    missing poller. Returns an empty summary when no live poller is configured (e.g. the
    in-process simulator) — there is nothing to poll."""
    if poller is None:
        return ReconciliationSummary()
    return reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)
