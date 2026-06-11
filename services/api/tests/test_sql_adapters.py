"""SQL adapters round-trip against an in-memory SQLite database.

Verifies the persistence logic (mapping, upsert, ledger grouping) with no running
Postgres. Production uses Postgres; the same adapter code targets both via SQLAlchemy.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from drc_pay_api.adapters.sql import Base, SqlLedger, SqlTransactionStore
from drc_pay_api.domains.ledger.ledger import Direction, Entry, Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.models import Transaction
from drc_pay_api.domains.transactions.state_machine import TxState


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _tx(tid: str = "t1", state: TxState = TxState.INITIATED) -> Transaction:
    return Transaction(
        id=tid,
        payer_msisdn="243a",
        payee_msisdn="243b",
        amount=Money(1000, "USD"),
        fee=Money(10, "USD"),
        state=state,
        history=[state],
    )


def test_store_roundtrip_and_update() -> None:
    store = SqlTransactionStore(_factory())
    store.save(_tx())
    got = store.get("t1")
    assert got.amount == Money(1000, "USD")
    assert got.fee == Money(10, "USD")
    assert got.state is TxState.INITIATED

    advanced = _tx(state=TxState.COLLECTION_PENDING)
    advanced.history = [TxState.INITIATED, TxState.COLLECTION_PENDING]
    store.save(advanced)
    reloaded = store.get("t1")
    assert reloaded.state is TxState.COLLECTION_PENDING
    assert reloaded.history == [TxState.INITIATED, TxState.COLLECTION_PENDING]


def test_store_get_missing_raises() -> None:
    store = SqlTransactionStore(_factory())
    try:
        store.get("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for a missing transaction")


def test_store_all() -> None:
    store = SqlTransactionStore(_factory())
    store.save(_tx("a"))
    store.save(_tx("b"))
    assert {t.id for t in store.all()} == {"a", "b"}


def test_ledger_post_and_read_grouped() -> None:
    factory = _factory()
    SqlTransactionStore(factory).save(_tx("tx1"))  # parent row (FK target)
    ledger = SqlLedger(factory)
    ledger.post(
        Posting(
            transaction_id="tx1",
            entries=(
                Entry("payer:external", Direction.DEBIT, Money(1010, "USD")),
                Entry("pawapay:clearing", Direction.CREDIT, Money(1010, "USD")),
            ),
        )
    )
    ledger.post(
        Posting(
            transaction_id="tx1",
            entries=(
                Entry("pawapay:clearing", Direction.DEBIT, Money(1010, "USD")),
                Entry("payee:external", Direction.CREDIT, Money(1000, "USD")),
                Entry("revenue:fees", Direction.CREDIT, Money(10, "USD")),
            ),
        )
    )
    postings = ledger.for_transaction("tx1")
    assert len(postings) == 2
    assert len(postings[0].entries) == 2  # collection posting
    assert len(postings[1].entries) == 3  # payout posting
    assert ledger.for_transaction("missing") == []


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_sql_adapters: all passed")
