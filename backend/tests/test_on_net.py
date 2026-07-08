"""On-net (same-network) payment: facilitate & record. The customer pays the merchant directly on the
operator's rail (we never touch the money); we record the payment as pending, then mark it paid on
confirmation — a single balanced ledger entry (customer → merchant), no fee. See ADR 0009.

Contrast with test_orchestrator.py (the routed/cross-network two-leg flow).
"""

from __future__ import annotations

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.domains.ledger.ledger import Direction, Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.on_net import OnNetOrchestrator
from drc_pay_api.domains.transactions.orchestrator import (
    CLEARING,
    CUSTOMER,
    EXPENSE,
    MERCHANT,
    REVENUE,
)
from drc_pay_api.domains.transactions.state_machine import TxState

USD = "USD"
PROVIDER = "AIRTEL_COD"


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
            total += (
                e.amount.amount_minor if e.direction is Direction.DEBIT else -e.amount.amount_minor
            )
    return total


def _make() -> tuple[OnNetOrchestrator, InMemoryTransactionStore, InMemoryLedger]:
    store, ledger = InMemoryTransactionStore(), InMemoryLedger()
    return OnNetOrchestrator(store, ledger), store, ledger


def test_on_net_success_is_one_posting_straight_to_merchant() -> None:
    orch, store, ledger = _make()
    amount = Money.from_major("10.00", USD)
    orch.start(
        transaction_id="o1",
        payer_msisdn="243aaa",
        merchant_msisdn="243bbb",
        amount=amount,
        provider=PROVIDER,
        merchant_id="m_demo",
    )
    # We initiate nothing on the operator — the payment is recorded as awaiting confirmation.
    assert store.get("o1").state is TxState.COLLECTION_PENDING
    assert ledger.postings == []  # nothing recorded until it's confirmed

    orch.on_confirm("o1", success=True)
    tx = store.get("o1")
    assert tx.state is TxState.PAYOUT_SUCCEEDED  # paid — the shared terminal
    assert tx.fee.amount_minor == 0  # we take no cut and pay no pawaPay leg
    assert len(ledger.postings) == 1  # ONE leg, not two
    assert (
        _credit_total(ledger.postings, MERCHANT) == amount.amount_minor
    )  # merchant got the full amount
    assert _net_debit(ledger.postings, CUSTOMER) == amount.amount_minor  # customer paid it
    # None of the routed-flow accounts are touched on-net (no custody, no pawaPay cost).
    assert _credit_total(ledger.postings, CLEARING) == 0
    assert _credit_total(ledger.postings, EXPENSE) == 0
    assert _credit_total(ledger.postings, REVENUE) == 0
    assert (tx.customer_provider, tx.merchant_provider) == (PROVIDER, PROVIDER)


def test_on_net_not_received_moves_no_money() -> None:
    orch, store, ledger = _make()
    orch.start(
        transaction_id="o2",
        payer_msisdn="243aaa",
        merchant_msisdn="243bbb",
        amount=Money.from_major("5.00", USD),
        provider=PROVIDER,
    )
    orch.on_confirm("o2", success=False)
    assert store.get("o2").state is TxState.COLLECTION_FAILED
    assert ledger.postings == []


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_on_net: all passed")
