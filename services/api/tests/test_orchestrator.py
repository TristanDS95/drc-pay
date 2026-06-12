"""The payment spine, end to end: happy path, refund, and terminal failures.

A customer pays a merchant: the customer pays the sticker amount, the merchant nets
amount − fee (it absorbs the MDR), and a failed settlement refunds the customer in full.
Every ledger posting self-validates (debits == credits), so a balanced book is proven by
construction.
"""
from __future__ import annotations

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.domains.ledger.ledger import Direction, Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.orchestrator import (
    CLEARING,
    CUSTOMER,
    MERCHANT,
    REVENUE,
    Orchestrator,
)
from drc_pay_api.domains.transactions.state_machine import TxState

from fakes import FakePaymentRail

USD = "USD"
CUSTOMER_PROV = "AIRTEL_COD"
MERCHANT_PROV = "ORANGE_COD"


def _make(
    reject_legs: set[str] | None = None,
) -> tuple[Orchestrator, InMemoryTransactionStore, FakePaymentRail, InMemoryLedger]:
    store = InMemoryTransactionStore()
    rail = FakePaymentRail(reject_legs)
    ledger = InMemoryLedger()
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


def _start(orch: Orchestrator, tid: str, amount: Money, fee: Money) -> None:
    orch.start_transaction(
        transaction_id=tid,
        customer_msisdn="243aaa",
        merchant_msisdn="243bbb",
        amount=amount,
        fee=fee,
        customer_provider=CUSTOMER_PROV,
        merchant_provider=MERCHANT_PROV,
        merchant_id="m_demo",
    )


def test_happy_path_settles_merchant_net_of_fee() -> None:
    orch, store, rail, ledger = _make()
    amount = Money.from_major("10.00", USD)
    fee = Money.from_major("0.50", USD)
    net = Money.from_major("9.50", USD)

    _start(orch, "t1", amount, fee)
    # The customer is charged exactly the sticker amount (no fee on top).
    assert rail.collections == [("t1", "243aaa", amount, CUSTOMER_PROV)]

    orch.on_collection_result("t1", success=True)
    # The merchant is settled amount − fee, on the merchant's operator.
    assert rail.payouts == [("t1", "243bbb", net, MERCHANT_PROV)]

    orch.on_payout_result("t1", success=True)
    final = store.get("t1")
    assert final.state is TxState.PAYOUT_SUCCEEDED
    assert len(ledger.postings) == 2  # collection + settlement
    assert _credit_total(ledger.postings, MERCHANT) == net.amount_minor
    assert _credit_total(ledger.postings, REVENUE) == fee.amount_minor
    # Providers, merchant link, and op-ids are persisted on the transaction.
    assert (final.customer_provider, final.merchant_provider) == (CUSTOMER_PROV, MERCHANT_PROV)
    assert final.merchant_id == "m_demo"
    assert (final.deposit_id, final.payout_id) == ("dep-t1", "pay-t1")


def test_settlement_failure_refunds_the_customer() -> None:
    orch, store, rail, ledger = _make()
    amount = Money.from_major("10.00", USD)
    fee = Money.from_major("0.50", USD)

    _start(orch, "t2", amount, fee)
    orch.on_collection_result("t2", success=True)
    orch.on_payout_result("t2", success=False)
    # The refund returns the full amount the customer paid, against the original deposit.
    assert rail.refunds == [("t2", "dep-t2", amount)]
    assert store.get("t2").state is TxState.REFUND_PENDING

    orch.on_refund_result("t2", success=True)
    refunded = store.get("t2")
    assert refunded.state is TxState.REFUNDED
    assert refunded.refund_id == "ref-t2"
    assert _credit_total(ledger.postings, REVENUE) == 0  # no fee on a refunded transaction
    assert _net_debit(ledger.postings, CUSTOMER) == 0  # customer made whole
    assert _net_debit(ledger.postings, CLEARING) == 0  # nothing left held


def test_collection_failure_moves_no_money() -> None:
    orch, store, rail, ledger = _make()
    _start(orch, "t3", Money.from_major("5.00", USD), Money.from_major("0.25", USD))
    orch.on_collection_result("t3", success=False)
    assert store.get("t3").state is TxState.COLLECTION_FAILED
    assert rail.payouts == []
    assert ledger.postings == []


def test_failed_refund_escalates_to_manual_review() -> None:
    orch, store, rail, ledger = _make()
    _start(orch, "t4", Money.from_major("5.00", USD), Money.from_major("0.25", USD))
    orch.on_collection_result("t4", success=True)
    orch.on_payout_result("t4", success=False)
    orch.on_refund_result("t4", success=False)
    assert store.get("t4").state is TxState.MANUAL_REVIEW


def test_fee_must_be_less_than_amount() -> None:
    orch, _, _, _ = _make()
    try:
        _start(orch, "t5", Money.from_major("1.00", USD), Money.from_major("1.00", USD))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when fee >= amount")


def test_synchronous_collection_reject_ends_clean() -> None:
    # pawaPay rejects the deposit synchronously (ack != ACCEPTED) → immediate fail.
    orch, store, rail, ledger = _make(reject_legs={"collection"})
    _start(orch, "r1", Money.from_major("10.00", USD), Money.from_major("0.10", USD))
    assert store.get("r1").state is TxState.COLLECTION_FAILED
    assert rail.payouts == []
    assert ledger.postings == []  # rejected before any money moved


def test_synchronous_settlement_reject_triggers_refund() -> None:
    orch, store, rail, ledger = _make(reject_legs={"payout"})
    _start(orch, "r2", Money.from_major("10.00", USD), Money.from_major("0.50", USD))
    orch.on_collection_result("r2", success=True)  # _begin_payout rejects → refund
    assert store.get("r2").state is TxState.REFUND_PENDING
    assert rail.refunds  # a refund was requested
    orch.on_refund_result("r2", success=True)
    assert store.get("r2").state is TxState.REFUNDED
    assert _net_debit(ledger.postings, CUSTOMER) == 0  # customer made whole


def test_synchronous_refund_reject_escalates_to_manual_review() -> None:
    orch, store, _, _ = _make(reject_legs={"refund"})
    _start(orch, "r3", Money.from_major("10.00", USD), Money.from_major("0.50", USD))
    orch.on_collection_result("r3", success=True)
    orch.on_payout_result("r3", success=False)  # _begin_refund rejects → manual_review
    assert store.get("r3").state is TxState.MANUAL_REVIEW


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_orchestrator: all passed")
