"""The reconciliation sweep — the missed-callback safety net — driven entirely offline.

Each test parks a transaction in a real pending state (a leg issued on a fake rail, awaiting
pawaPay), then runs the sweep against a mock status poller and asserts it resolves exactly as
the equivalent callback would: a polled COMPLETED advances the leg, a polled FAILED triggers a
refund, non-terminal / unreadable statuses leave the transaction untouched, and one bad poll
never takes the sweep down.
"""

from __future__ import annotations

import httpx

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.application.outcomes import AWAITING_STATE
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.models import Transaction
from drc_pay_api.domains.transactions.orchestrator import Orchestrator
from drc_pay_api.domains.transactions.state_machine import PENDING_STATES, TxState
from drc_pay_api.integrations.pawapay.status import Outcome, PawaPayStatus, classify
from drc_pay_api.jobs.reconciliation.sweep import (
    ALREADY_APPLIED,
    POLL_ERROR,
    RESOLVED_FAILURE,
    RESOLVED_SUCCESS,
    SKIPPED_NO_OP_ID,
    STILL_PENDING,
    UNRESOLVED,
    reconcile_pending,
    run_reconciliation,
)

from fakes import FakePaymentRail


class FakeStatusPoller:
    """Stands in for pawaPay's status endpoints: maps an op-id → a raw status string (or None
    for an unreadable status), and can be told to raise for given op-ids (a network failure)."""

    def __init__(self, statuses: dict[str, str | None], raise_for: set[str] | None = None) -> None:
        self._statuses = statuses
        self._raise_for = raise_for or set()
        self.polled: list[str] = []

    def _lookup(self, op_id: str) -> PawaPayStatus:
        self.polled.append(op_id)
        if op_id in self._raise_for:
            raise httpx.ConnectError("simulated network failure")
        return PawaPayStatus(self._statuses.get(op_id))

    def get_deposit_status(self, deposit_id: str) -> PawaPayStatus:
        return self._lookup(deposit_id)

    def get_payout_status(self, payout_id: str) -> PawaPayStatus:
        return self._lookup(payout_id)

    def get_refund_status(self, refund_id: str) -> PawaPayStatus:
        return self._lookup(refund_id)


def _setup() -> tuple[InMemoryTransactionStore, InMemoryLedger, FakePaymentRail, Orchestrator]:
    store = InMemoryTransactionStore()
    ledger = InMemoryLedger()
    rail = FakePaymentRail()
    return store, ledger, rail, Orchestrator(store, rail, ledger)


def _start(orch: Orchestrator, tid: str = "t1") -> None:
    """Issue a collection on the fake rail, parking the transaction in collection_pending with
    deposit_id ``dep-<tid>`` (exactly the pre-callback state a real deposit leaves)."""
    orch.start_transaction(
        transaction_id=tid,
        customer_msisdn="243800000001",
        merchant_msisdn="243810000002",
        amount=Money.from_major("10.00", "USD"),
        fee=Money.from_major("0.10", "USD"),
        customer_provider="VODACOM_MPESA_COD",
        merchant_provider="AIRTEL_COD",
    )


# ---- the resolving paths ----------------------------------------------------


def test_resolves_missed_deposit_callback() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    poller = FakeStatusPoller({"dep-t1": "COMPLETED"})

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.resolved == 1
    assert summary.count(RESOLVED_SUCCESS) == 1
    assert poller.polled == ["dep-t1"]
    tx = store.get("t1")
    assert tx.state is TxState.PAYOUT_PENDING  # collection applied → settlement issued
    assert len(rail.payouts) == 1  # the payout leg was kicked off, just as a callback would
    assert len(ledger.postings) == 1  # the collection posting


def test_resolves_missed_payout_failure_and_triggers_refund() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    orch.on_collection_result("t1", success=True)  # advance to payout_pending (payout_id pay-t1)
    assert store.get("t1").state is TxState.PAYOUT_PENDING
    poller = FakeStatusPoller({"pay-t1": "FAILED"})

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(RESOLVED_FAILURE) == 1
    assert store.get("t1").state is TxState.REFUND_PENDING  # failure auto-started the refund
    assert len(rail.refunds) == 1


# ---- the leave-it-alone paths -----------------------------------------------


def test_non_terminal_status_left_pending() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    poller = FakeStatusPoller({"dep-t1": "ACCEPTED"})  # pawaPay has it, not done yet

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(STILL_PENDING) == 1
    assert summary.resolved == 0
    assert store.get("t1").state is TxState.COLLECTION_PENDING  # untouched
    assert rail.payouts == []


def test_unreadable_status_left_unresolved() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    poller = FakeStatusPoller({"dep-t1": None})  # couldn't read a status (non-2xx / odd shape)

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(UNRESOLVED) == 1
    assert store.get("t1").state is TxState.COLLECTION_PENDING


def test_skips_pending_tx_with_no_op_id() -> None:
    # A transaction parked in a pending state without a pawaPay op-id (e.g. a simulator leg)
    # has nothing to poll — the sweep skips it rather than guessing.
    store, ledger, rail, _ = _setup()
    store.save(
        Transaction(
            id="t2",
            customer_msisdn="a",
            merchant_msisdn="b",
            amount=Money(1000, "USD"),
            fee=Money(10, "USD"),
            state=TxState.COLLECTION_PENDING,
            history=[TxState.COLLECTION_PENDING],
        )
    )
    poller = FakeStatusPoller({})

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(SKIPPED_NO_OP_ID) == 1
    assert poller.polled == []  # never reached the network


# ---- robustness -------------------------------------------------------------


def test_one_poll_error_does_not_abort_the_sweep() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch, "t1")
    _start(orch, "t2")
    # The first transaction's poll blows up; the second must still be reconciled.
    poller = FakeStatusPoller({"dep-t2": "COMPLETED"}, raise_for={"dep-t1"})

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(POLL_ERROR) == 1
    assert summary.count(RESOLVED_SUCCESS) == 1
    assert store.get("t1").state is TxState.COLLECTION_PENDING  # left for the next sweep
    assert store.get("t2").state is TxState.PAYOUT_PENDING  # resolved despite its sibling failing


class _RaceStore:
    """A store whose pending tx has, by the time the applier reads it, already advanced — as if
    a real callback resolved the leg between find_pending and apply. Exercises the guard."""

    def __init__(self, pending: Transaction, advanced: Transaction) -> None:
        self._pending = pending
        self._advanced = advanced
        self.saved: list[Transaction] = []

    def find_pending(self) -> list[Transaction]:
        return [self._pending]

    def get(self, transaction_id: str) -> Transaction:
        return self._advanced  # the callback already moved it on

    def save(self, transaction: Transaction) -> None:
        self.saved.append(transaction)


def test_callback_winning_the_race_is_a_noop() -> None:
    pending = Transaction(
        id="t1",
        customer_msisdn="a",
        merchant_msisdn="b",
        amount=Money(1000, "USD"),
        fee=Money(10, "USD"),
        state=TxState.COLLECTION_PENDING,
        history=[TxState.COLLECTION_PENDING],
        deposit_id="dep-t1",
    )
    advanced = Transaction(
        id="t1",
        customer_msisdn="a",
        merchant_msisdn="b",
        amount=Money(1000, "USD"),
        fee=Money(10, "USD"),
        state=TxState.PAYOUT_PENDING,  # a callback got here first
        history=[TxState.COLLECTION_PENDING, TxState.PAYOUT_PENDING],
        deposit_id="dep-t1",
    )
    store = _RaceStore(pending, advanced)
    _, ledger, rail, _ = _setup()
    poller = FakeStatusPoller({"dep-t1": "COMPLETED"})

    summary = reconcile_pending(store=store, rail=rail, ledger=ledger, poller=poller)

    assert summary.count(ALREADY_APPLIED) == 1
    assert store.saved == []  # the guard tripped before any state change


# ---- composition entry + invariants -----------------------------------------


def test_run_reconciliation_without_poller_is_a_noop() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    summary = run_reconciliation(store=store, rail=rail, ledger=ledger, poller=None)
    assert summary.total == 0
    assert store.get("t1").state is TxState.COLLECTION_PENDING  # nothing polled, nothing changed


def test_run_reconciliation_with_poller_resolves() -> None:
    store, ledger, rail, orch = _setup()
    _start(orch)
    poller = FakeStatusPoller({"dep-t1": "COMPLETED"})
    summary = run_reconciliation(store=store, rail=rail, ledger=ledger, poller=poller)
    assert summary.count(RESOLVED_SUCCESS) == 1


def test_awaiting_states_match_pending_states() -> None:
    # The webhook guard and the sweep's worklist must describe the same set of states, or a
    # missed callback in one of them would never be reconciled.
    assert set(AWAITING_STATE.values()) == PENDING_STATES


def test_classify_terminal_vocabulary() -> None:
    assert classify("COMPLETED") is Outcome.SUCCESS
    assert classify("completed") is Outcome.SUCCESS  # case-insensitive
    assert classify("FAILED") is Outcome.FAILURE
    assert classify("REJECTED") is Outcome.FAILURE
    assert classify("ACCEPTED") is Outcome.PENDING
    assert classify("") is Outcome.PENDING
    assert classify(None) is Outcome.PENDING


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_reconciliation: all passed")
