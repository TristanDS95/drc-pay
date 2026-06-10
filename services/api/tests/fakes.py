"""In-memory fakes for testing the orchestrator offline and deterministically.

These stand in for the real adapters (pawaPay client, Postgres repo, ledger) so the
payment spine can be exercised — including every failure branch — with no network and
no database. They mirror the Protocols in ``domains.transactions.ports``.
"""
from __future__ import annotations

from drc_pay_api.domains.ledger.ledger import Posting
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.models import Transaction


class FakePaymentRail:
    """Records every request instead of calling pawaPay. Outcomes are delivered
    separately by the test via the orchestrator's ``on_*_result`` handlers."""

    def __init__(self) -> None:
        self.collections: list[tuple[str, str, Money]] = []
        self.payouts: list[tuple[str, str, Money]] = []
        self.refunds: list[str] = []

    def request_collection(self, *, transfer_id: str, msisdn: str, amount: Money) -> None:
        self.collections.append((transfer_id, msisdn, amount))

    def request_payout(self, *, transfer_id: str, msisdn: str, amount: Money) -> None:
        self.payouts.append((transfer_id, msisdn, amount))

    def request_refund(self, *, transfer_id: str) -> None:
        self.refunds.append(transfer_id)


class InMemoryTransactionStore:
    def __init__(self) -> None:
        self._rows: dict[str, Transaction] = {}

    def get(self, transfer_id: str) -> Transaction:
        return self._rows[transfer_id]

    def save(self, transaction: Transaction) -> None:
        self._rows[transaction.id] = transaction


class RecordingLedger:
    def __init__(self) -> None:
        self.postings: list[Posting] = []

    def post(self, posting: Posting) -> None:
        self.postings.append(posting)
