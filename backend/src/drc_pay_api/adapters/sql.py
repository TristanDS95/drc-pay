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
    or_,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..domains.auth.models import MerchantCredential, MerchantSession
from ..domains.charges.models import Charge
from ..domains.ledger.ledger import Direction, Entry, Posting
from ..domains.ledger.money import Money
from ..domains.merchants.models import Merchant
from ..domains.transactions.models import Transaction
from ..domains.transactions.state_machine import PENDING_STATES, TxState


class Base(DeclarativeBase):
    pass


class MerchantRow(Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    short_code: Mapped[str] = mapped_column(String, unique=True)
    settlement_msisdn: Mapped[str] = mapped_column(String)
    settlement_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    # The merchant's own operator "buy goods" till (on-net hand-off prefers it). See ADR 0009.
    operator_till: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MerchantCredentialRow(Base):
    """A merchant's login. Stores only the Argon2id hash — never a password."""

    __tablename__ = "merchant_credentials"

    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), primary_key=True
    )
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MerchantSessionRow(Base):
    """A live login. Keyed by the SHA-256 of the bearer token — the token itself is
    never persisted, so a database read cannot mint a valid Authorization header."""

    __tablename__ = "merchant_sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChargeRow(Base):
    """A merchant-posted charge (checkout). Its status is derived from the linked transaction, so
    no status column here — only the link."""

    __tablename__ = "charges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String)
    transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_msisdn: Mapped[str] = mapped_column(String)
    merchant_msisdn: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    fee_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    history: Mapped[list[str]] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Resolved pawaPay operator codes (customer's for collection/refund, merchant's for settlement).
    customer_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    merchant_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    # pawaPay operation ids, for callback correlation and refund referencing.
    deposit_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payout_id: Mapped[str | None] = mapped_column(String, nullable=True)
    refund_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Assurance level: "rail_verified" (pawaPay) or "merchant_attested" (on-net). See ADR 0009.
    provenance: Mapped[str] = mapped_column(String, server_default="rail_verified")
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


def normalize_db_url(url: str) -> str:
    """Managed Postgres providers (Railway, Render, Heroku) hand out a ``postgres://`` or
    ``postgresql://`` URL; SQLAlchemy with psycopg3 needs the ``postgresql+psycopg://`` driver.
    Shared by the app engine and the Alembic migrations (``migrations/env.py``)."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str) -> Engine:
    return create_engine(normalize_db_url(url))


# Note: the schema is created/evolved by Alembic migrations (`alembic upgrade head`),
# not auto-created at runtime — see migrations/. Tests build their own schema directly
# with `Base.metadata.create_all` against in-memory SQLite.


def _to_domain(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        customer_msisdn=row.customer_msisdn,
        merchant_msisdn=row.merchant_msisdn,
        amount=Money(row.amount_minor, row.currency),
        fee=Money(row.fee_minor, row.currency),
        state=TxState(row.state),
        history=[TxState(s) for s in row.history],
        idempotency_key=row.idempotency_key,
        merchant_id=row.merchant_id,
        customer_provider=row.customer_provider,
        merchant_provider=row.merchant_provider,
        deposit_id=row.deposit_id,
        payout_id=row.payout_id,
        refund_id=row.refund_id,
        provenance=row.provenance,
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
            row.customer_msisdn = transaction.customer_msisdn
            row.merchant_msisdn = transaction.merchant_msisdn
            row.amount_minor = transaction.amount.amount_minor
            row.fee_minor = transaction.fee.amount_minor
            row.currency = transaction.amount.currency
            row.state = transaction.state.value
            row.history = [s.value for s in transaction.history]
            row.idempotency_key = transaction.idempotency_key
            row.merchant_id = transaction.merchant_id
            row.customer_provider = transaction.customer_provider
            row.merchant_provider = transaction.merchant_provider
            row.deposit_id = transaction.deposit_id
            row.payout_id = transaction.payout_id
            row.refund_id = transaction.refund_id
            row.provenance = transaction.provenance
            session.commit()

    def all(self) -> list[Transaction]:
        with self._sf() as session:
            rows = session.scalars(select(TransactionRow).order_by(TransactionRow.created_at)).all()
            return [_to_domain(row) for row in rows]

    def find_by_idempotency_key(self, key: str) -> Transaction | None:
        with self._sf() as session:
            row = session.scalars(
                select(TransactionRow).where(TransactionRow.idempotency_key == key)
            ).first()
            return _to_domain(row) if row is not None else None

    def find_by_op_id(self, op_id: str) -> Transaction | None:
        with self._sf() as session:
            row = session.scalars(
                select(TransactionRow).where(
                    or_(
                        TransactionRow.deposit_id == op_id,
                        TransactionRow.payout_id == op_id,
                        TransactionRow.refund_id == op_id,
                    )
                )
            ).first()
            return _to_domain(row) if row is not None else None

    def find_pending(self) -> list[Transaction]:
        """Transactions awaiting an async rail outcome — the reconciliation sweep's worklist."""
        with self._sf() as session:
            rows = session.scalars(
                select(TransactionRow)
                .where(TransactionRow.state.in_([s.value for s in PENDING_STATES]))
                .order_by(TransactionRow.created_at)
            ).all()
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


def _merchant_to_domain(row: MerchantRow) -> Merchant:
    return Merchant(
        id=row.id,
        name=row.name,
        short_code=row.short_code,
        settlement_msisdn=row.settlement_msisdn,
        settlement_provider=row.settlement_provider,
        status=row.status,
        operator_till=row.operator_till,
    )


class SqlMerchantStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(self, merchant_id: str) -> Merchant:
        with self._sf() as session:
            row = session.get(MerchantRow, merchant_id)
            if row is None:
                raise KeyError(merchant_id)
            return _merchant_to_domain(row)

    def get_by_short_code(self, short_code: str) -> Merchant | None:
        with self._sf() as session:
            row = session.scalars(
                select(MerchantRow).where(MerchantRow.short_code == short_code)
            ).first()
            return _merchant_to_domain(row) if row is not None else None

    def save(self, merchant: Merchant) -> None:
        with self._sf() as session:
            row = session.get(MerchantRow, merchant.id)
            if row is None:
                row = MerchantRow(id=merchant.id)
                session.add(row)
            row.name = merchant.name
            row.short_code = merchant.short_code
            row.settlement_msisdn = merchant.settlement_msisdn
            row.settlement_provider = merchant.settlement_provider
            row.status = merchant.status
            row.operator_till = merchant.operator_till
            session.commit()

    def all(self) -> list[Merchant]:
        with self._sf() as session:
            rows = session.scalars(select(MerchantRow).order_by(MerchantRow.created_at)).all()
            return [_merchant_to_domain(row) for row in rows]


class SqlCredentialStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get_by_username(self, username: str) -> MerchantCredential | None:
        with self._sf() as session:
            row = session.scalars(
                select(MerchantCredentialRow).where(MerchantCredentialRow.username == username)
            ).first()
            return self._to_domain(row) if row is not None else None

    def save(self, credential: MerchantCredential) -> None:
        with self._sf() as session:
            row = session.get(MerchantCredentialRow, credential.merchant_id)
            if row is None:
                row = MerchantCredentialRow(merchant_id=credential.merchant_id)
                session.add(row)
            row.username = credential.username
            row.password_hash = credential.password_hash
            session.commit()

    @staticmethod
    def _to_domain(row: MerchantCredentialRow) -> MerchantCredential:
        return MerchantCredential(
            merchant_id=row.merchant_id, username=row.username, password_hash=row.password_hash
        )


class SqlSessionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(self, token_hash: str) -> MerchantSession | None:
        with self._sf() as session:
            row = session.get(MerchantSessionRow, token_hash)
            if row is None:
                return None
            return MerchantSession(
                token_hash=row.token_hash,
                merchant_id=row.merchant_id,
                expires_at=row.expires_at,
            )

    def save(self, merchant_session: MerchantSession) -> None:
        with self._sf() as session:
            row = session.get(MerchantSessionRow, merchant_session.token_hash)
            if row is None:
                row = MerchantSessionRow(token_hash=merchant_session.token_hash)
                session.add(row)
            row.merchant_id = merchant_session.merchant_id
            row.expires_at = merchant_session.expires_at
            session.commit()

    def delete(self, token_hash: str) -> None:
        with self._sf() as session:
            row = session.get(MerchantSessionRow, token_hash)
            if row is not None:
                session.delete(row)
                session.commit()


def _charge_to_domain(row: ChargeRow) -> Charge:
    return Charge(
        id=row.id,
        merchant_id=row.merchant_id,
        amount=Money(row.amount_minor, row.currency),
        transaction_id=row.transaction_id,
    )


class SqlChargeStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(self, charge_id: str) -> Charge:
        with self._sf() as session:
            row = session.get(ChargeRow, charge_id)
            if row is None:
                raise KeyError(charge_id)
            return _charge_to_domain(row)

    def save(self, charge: Charge) -> None:
        with self._sf() as session:
            row = session.get(ChargeRow, charge.id)
            if row is None:
                row = ChargeRow(id=charge.id)
                session.add(row)
            row.merchant_id = charge.merchant_id
            row.amount_minor = charge.amount.amount_minor
            row.currency = charge.amount.currency
            row.transaction_id = charge.transaction_id
            session.commit()

    def all(self) -> list[Charge]:
        with self._sf() as session:
            rows = session.scalars(select(ChargeRow).order_by(ChargeRow.created_at)).all()
            return [_charge_to_domain(row) for row in rows]
