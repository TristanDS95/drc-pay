"""Composition root — holds the shared, persistent adapters.

Selects the persistence backend from config: if a database URL is provided, the
Postgres-backed SQLAlchemy adapters are used; otherwise the in-memory adapters (which
keep the demo working with zero setup). The pawaPay simulator stands in for the rail
either way. The orchestrator itself is built per-request (in ``routes``) with a fresh
trace recorder, so each call can return its own operations log.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import sessionmaker

from ..adapters.memory import InMemoryLedger, InMemoryTransactionStore
from ..adapters.sql import SqlLedger, SqlTransactionStore, make_engine
from ..domains.ledger.ledger import Posting
from ..domains.transactions.models import Transaction
from ..integrations.pawapay.simulator import SimulatedPaymentRail


class TxStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...

    def all(self) -> list[Transaction]: ...

    def find_by_idempotency_key(self, key: str) -> Transaction | None: ...


class LedgerStore(Protocol):
    def post(self, posting: Posting) -> None: ...

    def for_transaction(self, transaction_id: str) -> list[Posting]: ...


@dataclass
class Container:
    store: TxStore
    ledger: LedgerStore
    rail: SimulatedPaymentRail


def build_container(database_url: str = "") -> Container:
    rail = SimulatedPaymentRail()
    if database_url:
        # Schema is managed by Alembic (`alembic upgrade head`), not created here.
        engine = make_engine(database_url)
        session_factory = sessionmaker(engine)
        return Container(SqlTransactionStore(session_factory), SqlLedger(session_factory), rail)
    return Container(InMemoryTransactionStore(), InMemoryLedger(), rail)
