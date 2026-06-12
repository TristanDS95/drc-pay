"""In-memory adapters: a transaction store, a ledger, and a trace recorder.

Good enough for local dev, the built-in simulator, and tests. The production versions
(Postgres, append-only ledger, real logging) implement the same ports and slot in
unchanged.
"""
from __future__ import annotations

from ..domains.ledger.ledger import Posting
from ..domains.merchants.models import Merchant
from ..domains.transactions.models import Transaction


class InMemoryMerchantStore:
    def __init__(self) -> None:
        self._rows: dict[str, Merchant] = {}

    def get(self, merchant_id: str) -> Merchant:
        return self._rows[merchant_id]

    def get_by_short_code(self, short_code: str) -> Merchant | None:
        for merchant in self._rows.values():
            if merchant.short_code == short_code:
                return merchant
        return None

    def save(self, merchant: Merchant) -> None:
        self._rows[merchant.id] = merchant

    def all(self) -> list[Merchant]:
        return list(self._rows.values())


class InMemoryTransactionStore:
    def __init__(self) -> None:
        self._rows: dict[str, Transaction] = {}

    def get(self, transaction_id: str) -> Transaction:
        return self._rows[transaction_id]

    def save(self, transaction: Transaction) -> None:
        self._rows[transaction.id] = transaction

    def all(self) -> list[Transaction]:
        return list(self._rows.values())

    def find_by_idempotency_key(self, key: str) -> Transaction | None:
        for transaction in self._rows.values():
            if transaction.idempotency_key == key:
                return transaction
        return None

    def find_by_op_id(self, op_id: str) -> Transaction | None:
        for transaction in self._rows.values():
            if op_id in (transaction.deposit_id, transaction.payout_id, transaction.refund_id):
                return transaction
        return None


class InMemoryLedger:
    def __init__(self) -> None:
        self.postings: list[Posting] = []

    def post(self, posting: Posting) -> None:
        self.postings.append(posting)

    def for_transaction(self, transaction_id: str) -> list[Posting]:
        return [p for p in self.postings if p.transaction_id == transaction_id]


class ListRecorder:
    """Collects the orchestrator's narration into a list — the source of the
    operations trace returned by the API."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def record(self, message: str) -> None:
        self.messages.append(message)
