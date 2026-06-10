"""In-memory adapters: a transaction store and a ledger that live in process.

Good enough for local dev, the built-in simulator, and tests. The production versions
(Postgres, append-only) implement the same ports and slot in unchanged.
"""
from __future__ import annotations

from ..domains.ledger.ledger import Posting
from ..domains.transactions.models import Transaction


class InMemoryTransactionStore:
    def __init__(self) -> None:
        self._rows: dict[str, Transaction] = {}

    def get(self, transfer_id: str) -> Transaction:
        return self._rows[transfer_id]

    def save(self, transaction: Transaction) -> None:
        self._rows[transaction.id] = transaction

    def all(self) -> list[Transaction]:
        return list(self._rows.values())


class InMemoryLedger:
    def __init__(self) -> None:
        self.postings: list[Posting] = []

    def post(self, posting: Posting) -> None:
        self.postings.append(posting)

    def for_transaction(self, transaction_id: str) -> list[Posting]:
        return [p for p in self.postings if p.transaction_id == transaction_id]
