"""Ledger: balanced postings succeed, unbalanced postings are rejected."""
from __future__ import annotations

from drc_pay_api.domains.ledger.ledger import (
    Direction,
    Entry,
    Posting,
    UnbalancedPosting,
)
from drc_pay_api.domains.ledger.money import Money


def test_balanced_posting_ok() -> None:
    # Payer debited 10.50; payout account credited 10.00; fee revenue credited 0.50.
    posting = Posting(
        transaction_id="tx_1",
        entries=(
            Entry("payer:wallet", Direction.DEBIT, Money(1050, "USD")),
            Entry("payout:wallet", Direction.CREDIT, Money(1000, "USD")),
            Entry("revenue:fees", Direction.CREDIT, Money(50, "USD")),
        ),
    )
    assert len(posting.entries) == 3


def test_unbalanced_posting_raises() -> None:
    try:
        Posting(
            transaction_id="tx_2",
            entries=(
                Entry("payer:wallet", Direction.DEBIT, Money(1050, "USD")),
                Entry("payout:wallet", Direction.CREDIT, Money(1000, "USD")),
            ),
        )
    except UnbalancedPosting:
        pass
    else:
        raise AssertionError("expected UnbalancedPosting")


def test_single_entry_rejected() -> None:
    try:
        Posting(
            transaction_id="tx_3",
            entries=(Entry("payer:wallet", Direction.DEBIT, Money(1050, "USD")),),
        )
    except UnbalancedPosting:
        pass
    else:
        raise AssertionError("expected UnbalancedPosting for a single-entry posting")


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_ledger: all passed")
