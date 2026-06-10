"""The payment spine, end to end: happy path, refund, and terminal failures.

Every money movement is asserted, and because every ledger posting self-validates
(debits == credits), a balanced book is proven implicitly by construction.
"""
from __future__ import annotations

from drc_pay_api.domains.ledger.ledger import Direction, Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.orchestrator import (
    CLEARING,
    PAYEE,
    PAYER,
    REVENUE,
    Orchestrator,
)
from drc_pay_api.domains.transactions.state_machine import TxState

from fakes import FakePaymentRail, InMemoryTransactionStore, RecordingLedger

USD = "USD"


def _make() -> tuple[Orchestrator, InMemoryTransactionStore, FakePaymentRail, RecordingLedger]:
    store = InMemoryTransactionStore()
    rail = FakePaymentRail()
    ledger = RecordingLedger()
    return Orchestrator(store, rail, ledger), store, rail, ledger


def _credit_total(postings: list[Posting], account: str) -> int:
    return sum(
        e.amount.amount_minor
        for p in postings
        for e in p.entries
        if e.account == account and e.direction is Direction.CREDIT
    )


def _net_debit(postings: list[Posting], account: str) -> int:
    total = 0
    for p in postings:
        for e in p.entries:
            if e.account != account:
                continue
            total += e.amount.amount_minor if e.direction is Direction.DEBIT else -e.amount.amount_minor
    return total


def test_happy_path_delivers_amount_and_books_fee() -> None:
    orch, store, rail, ledger = _make()
    amount = Money.from_major("10.00", USD)
    fee = Money.from_major("0.50", USD)

    orch.start_transfer(
        transfer_id="t1", payer_msisdn="243aaa", payee_msisdn="243bbb", amount=amount, fee=fee
    )
    # The payer is charged amount + fee.
    assert rail.collections == [("t1", "243aaa", Money.from_major("10.50", USD))]

    orch.on_collection_result("t1", success=True)
    # The payee is paid exactly the amount (not the fee).
    assert rail.payouts == [("t1", "243bbb", amount)]

    orch.on_payout_result("t1", success=True)
    assert store.get("t1").state is TxState.PAYOUT_SUCCEEDED
    assert len(ledger.postings) == 2  # collection + payout
    assert _credit_total(ledger.postings, REVENUE) == fee.amount_minor
    assert _credit_total(ledger.postings, PAYEE) == amount.amount_minor


def test_payout_failure_refunds_the_payer() -> None:
    orch, store, rail, ledger = _make()
    amount = Money.from_major("10.00", USD)
    fee = Money.from_major("0.50", USD)

    orch.start_transfer(
        transfer_id="t2", payer_msisdn="243aaa", payee_msisdn="243bbb", amount=amount, fee=fee
    )
    orch.on_collection_result("t2", success=True)
    orch.on_payout_result("t2", success=False)
    assert rail.refunds == ["t2"]
    assert store.get("t2").state is TxState.REFUND_PENDING

    orch.on_refund_result("t2", success=True)
    assert store.get("t2").state is TxState.REFUNDED
    assert _credit_total(ledger.postings, REVENUE) == 0  # no fee on a refunded transfer
    assert _net_debit(ledger.postings, PAYER) == 0  # payer made whole
    assert _net_debit(ledger.postings, CLEARING) == 0  # nothing left held


def test_collection_failure_moves_no_money() -> None:
    orch, store, rail, ledger = _make()
    orch.start_transfer(
        transfer_id="t3",
        payer_msisdn="x",
        payee_msisdn="y",
        amount=Money.from_major("5.00", USD),
        fee=Money.from_major("0.25", USD),
    )
    orch.on_collection_result("t3", success=False)
    assert store.get("t3").state is TxState.COLLECTION_FAILED
    assert rail.payouts == []
    assert ledger.postings == []


def test_failed_refund_escalates_to_manual_review() -> None:
    orch, store, rail, ledger = _make()
    orch.start_transfer(
        transfer_id="t4",
        payer_msisdn="x",
        payee_msisdn="y",
        amount=Money.from_major("5.00", USD),
        fee=Money.from_major("0.25", USD),
    )
    orch.on_collection_result("t4", success=True)
    orch.on_payout_result("t4", success=False)
    orch.on_refund_result("t4", success=False)
    assert store.get("t4").state is TxState.MANUAL_REVIEW


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_orchestrator: all passed")
