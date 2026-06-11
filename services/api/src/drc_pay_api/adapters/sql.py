"""SQLAlchemy-backed adapters — the production persistence for transactions and the
ledger. They implement the same ports as the in-memory adapters, so swapping them in is
a one-line change in the composition root.

Schema (Postgres in production; the same code runs on SQLite for fast unit tests):
  - transactions    : one row per transfer (workflow state + ordered state history)
  - ledger_entries  : append-only double-entry lines, grouped by posting_id
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..domains.ledger.ledger import Direction, Entry, Posting
from ..domains.ledger.money import Money
from ..domains.transactions.models import Transaction
from ..domains.transactions.state_machine import TxState


class Base(DeclarativeBase):
    pass


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payer_msisdn: Mapped[str] = mapped_column(String)
    payee_msisdn: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    fee_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    history: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LedgerEntryRow(Base):
    """Append-only: rows are inserted, never updated or deleted."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    posting_id: Mapped[str] = mapped_column(String, index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    account: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def make_engine(url: str) -> Engine:
    return create_engine(url)


def init_db(engine: Engine) -> None:
    """Create tables if they don't exist. (Alembic migrations replace this later.)"""
    Base.metadata.create_all(engine)


def _to_domain(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        payer_msisdn=row.payer_msisdn,
        payee_msisdn=row.payee_msisdn,
        amount=Money(row.amount_minor, row.currency),
        fee=Money(row.fee_minor, row.currency),
        state=TxState(row.state),
        history=[TxState(s) for s in row.history],
    )


class SqlTransactionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(self, transaction_id: str) -> Transaction:
        with self._sf() as session:
            row = session.get(TransactionRow, transaction_id)
            if row is None:
                raise KeyError(transaction_id)
            return _to_domain(row)

    def save(self, transaction: Transaction) -> None:
        with self._sf() as session:
            row = session.get(TransactionRow, transaction.id)
            if row is None:
                row = TransactionRow(id=transaction.id)
                session.add(row)
            row.payer_msisdn = transaction.payer_msisdn
            row.payee_msisdn = transaction.payee_msisdn
            row.amount_minor = transaction.amount.amount_minor
            row.fee_minor = transaction.fee.amount_minor
            row.currency = transaction.amount.currency
            row.state = transaction.state.value
            row.history = [s.value for s in transaction.history]
            session.commit()

    def all(self) -> list[Transaction]:
        with self._sf() as session:
            rows = session.scalars(select(TransactionRow).order_by(TransactionRow.created_at)).all()
            return [_to_domain(row) for row in rows]


class SqlLedger:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def post(self, posting: Posting) -> None:
        posting_id = uuid.uuid4().hex
        with self._sf() as session:
            for entry in posting.entries:
                session.add(
                    LedgerEntryRow(
                        posting_id=posting_id,
                        transaction_id=posting.transaction_id,
                        account=entry.account,
                        direction=entry.direction.value,
                        amount_minor=entry.amount.amount_minor,
                        currency=entry.amount.currency,
                    )
                )
            session.commit()

    def for_transaction(self, transaction_id: str) -> list[Posting]:
        with self._sf() as session:
            rows = session.scalars(
                select(LedgerEntryRow)
                .where(LedgerEntryRow.transaction_id == transaction_id)
                .order_by(LedgerEntryRow.id)
            ).all()
        groups: dict[str, list[Entry]] = {}
        order: list[str] = []
        for row in rows:
            if row.posting_id not in groups:
                groups[row.posting_id] = []
                order.append(row.posting_id)
            groups[row.posting_id].append(
                Entry(row.account, Direction(row.direction), Money(row.amount_minor, row.currency))
            )
        return [Posting(transaction_id=transaction_id, entries=tuple(groups[pid])) for pid in order]
