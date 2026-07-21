"""SQL adapters round-trip against an in-memory SQLite database.

Verifies the persistence logic (mapping, upsert, ledger grouping) with no running
Postgres. Production uses Postgres; the same adapter code targets both via SQLAlchemy.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from drc_pay_api.adapters.sql import (
    Base,
    SqlLedger,
    SqlMerchantStore,
    SqlStaffCredentialStore,
    SqlStaffSessionStore,
    SqlTransactionStore,
    normalize_db_url,
)
from drc_pay_api.domains.ledger.ledger import Direction, Entry, Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.merchants.models import Merchant
from drc_pay_api.domains.staff.models import StaffCredential, StaffSession
from drc_pay_api.domains.transactions.models import Transaction
from drc_pay_api.domains.transactions.ports import DuplicateIdempotencyKey
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
        customer_msisdn="243a",
        merchant_msisdn="243b",
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


def test_store_persists_providers_op_ids_and_merchant() -> None:
    store = SqlTransactionStore(_factory())
    tx = _tx("t9")
    tx.merchant_id = "m_alpha"
    tx.customer_provider = "AIRTEL_COD"
    tx.merchant_provider = "ORANGE_COD"
    tx.deposit_id = "dep-9"
    tx.payout_id = "pay-9"
    tx.refund_id = "ref-9"
    store.save(tx)
    got = store.get("t9")
    assert got.merchant_id == "m_alpha"
    assert got.customer_provider == "AIRTEL_COD"
    assert got.merchant_provider == "ORANGE_COD"
    assert (got.deposit_id, got.payout_id, got.refund_id) == ("dep-9", "pay-9", "ref-9")


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
                Entry("customer:external", Direction.DEBIT, Money(1000, "USD")),
                Entry("pawapay:clearing", Direction.CREDIT, Money(1000, "USD")),
            ),
        )
    )
    ledger.post(
        Posting(
            transaction_id="tx1",
            entries=(
                Entry("pawapay:clearing", Direction.DEBIT, Money(1000, "USD")),
                Entry("merchant:external", Direction.CREDIT, Money(990, "USD")),
                Entry("revenue:fees", Direction.CREDIT, Money(10, "USD")),
            ),
        )
    )
    postings = ledger.for_transaction("tx1")
    assert len(postings) == 2
    assert len(postings[0].entries) == 2  # collection posting
    assert len(postings[1].entries) == 3  # payout posting
    assert ledger.for_transaction("missing") == []


def test_find_by_idempotency_key() -> None:
    store = SqlTransactionStore(_factory())
    tx = _tx("t1")
    tx.idempotency_key = "key-1"
    store.save(tx)
    found = store.find_by_idempotency_key("key-1")
    assert found is not None
    assert found.id == "t1"
    assert store.find_by_idempotency_key("missing") is None


def test_sql_store_rejects_a_second_transaction_under_the_same_key() -> None:
    # The DB unique constraint is the atomic backstop against a double charge when two requests
    # race past the pre-check; the store translates it to a domain error, not a raw IntegrityError.
    store = SqlTransactionStore(_factory())
    first = _tx("t1")
    first.idempotency_key = "dup"
    store.save(first)
    second = _tx("t2")  # different transaction id, same key
    second.idempotency_key = "dup"
    with pytest.raises(DuplicateIdempotencyKey):
        store.save(second)
    # Re-saving the SAME transaction (the normal state-transition path) is still fine.
    first.state = TxState.COLLECTION_PENDING
    store.save(first)


def test_merchant_store_roundtrip_and_lookup() -> None:
    store = SqlMerchantStore(_factory())
    store.save(
        Merchant(
            id="m1",
            name="Alpha Gas Station",
            short_code="1001",
            settlement_msisdn="243810000001",
            settlement_provider="AIRTEL_COD",
            operator_till="507412",
        )
    )
    got = store.get("m1")
    assert got.name == "Alpha Gas Station"
    assert got.is_active
    assert got.operator_till == "507412"  # the on-net till round-trips through SQL
    assert store.get_by_short_code("1001") is not None
    assert store.get_by_short_code("nope") is None


def test_find_by_op_id() -> None:
    store = SqlTransactionStore(_factory())
    tx = _tx("t7")
    tx.deposit_id = "dep-xyz"
    tx.payout_id = "pay-xyz"
    store.save(tx)
    found = store.find_by_op_id("dep-xyz")
    assert found is not None and found.id == "t7"
    assert store.find_by_op_id("pay-xyz") is not None  # matches any of deposit/payout/refund
    assert store.find_by_op_id("nope") is None


def test_normalize_db_url() -> None:
    # Managed providers hand out postgres:// or postgresql://; SQLAlchemy needs +psycopg.
    assert normalize_db_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_db_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_db_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite://") == "sqlite://"


def test_staff_credential_store_roundtrip_and_upsert() -> None:
    store = SqlStaffCredentialStore(_factory())
    store.save(StaffCredential(staff_id="s1", username="admin", password_hash="h1", role="admin"))
    by_user = store.get_by_username("admin")
    assert by_user is not None and by_user.staff_id == "s1" and by_user.role == "admin"
    by_id = store.get_by_id("s1")
    assert by_id is not None and by_id.username == "admin"
    # upsert by staff_id — a re-save updates hash + role in place
    store.save(
        StaffCredential(staff_id="s1", username="admin", password_hash="h2", role="superadmin")
    )
    updated = store.get_by_id("s1")
    assert updated is not None and updated.password_hash == "h2" and updated.role == "superadmin"
    assert store.get_by_username("ghost") is None
    assert store.get_by_id("nope") is None


def test_staff_session_store_roundtrip_and_delete() -> None:
    from datetime import UTC, datetime, timedelta

    store = SqlStaffSessionStore(_factory())
    expires = datetime.now(UTC) + timedelta(hours=1)
    store.save(StaffSession(token_hash="th1", staff_id="s1", expires_at=expires))
    got = store.get("th1")
    assert got is not None and got.staff_id == "s1"
    store.delete("th1")
    assert store.get("th1") is None


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_sql_adapters: all passed")


def test_staff_removal_deletes_sessions_then_credential() -> None:
    """The FK staff_sessions.staff_id -> staff_credentials.staff_id means sessions must go first;
    this exercises that order against a real SQL backend."""
    from datetime import UTC, datetime, timedelta

    factory = _factory()
    creds = SqlStaffCredentialStore(factory)
    sessions = SqlStaffSessionStore(factory)
    creds.save(StaffCredential(staff_id="s1", username="admin", password_hash="h", role="admin"))
    creds.save(StaffCredential(staff_id="s2", username="alice", password_hash="h", role="admin"))
    expires = datetime.now(UTC) + timedelta(hours=1)
    sessions.save(StaffSession(token_hash="t1", staff_id="s1", expires_at=expires))
    sessions.save(StaffSession(token_hash="t2", staff_id="s1", expires_at=expires))
    sessions.save(StaffSession(token_hash="keep", staff_id="s2", expires_at=expires))

    assert sessions.delete_for_staff("s1") == 2
    creds.delete("s1")

    assert creds.get_by_username("admin") is None
    assert sessions.get("t1") is None and sessions.get("t2") is None
    assert sessions.get("keep") is not None  # the other account's session survives
    assert [c.username for c in creds.all()] == ["alice"]
