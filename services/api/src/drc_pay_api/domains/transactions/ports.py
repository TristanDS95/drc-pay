"""Ports — the interfaces the orchestrator depends on (ports-and-adapters).

The orchestrator talks only to these abstractions, never to concrete infrastructure.
The real adapters live elsewhere:
  - ``PaymentRail``      -> the pawaPay client in ``integrations.pawapay`` (and the
                            local ``tooling/pawapay-sim`` fake)
  - ``TransactionStore`` -> a Postgres-backed repository
  - ``LedgerPort``       -> the append-only double-entry ledger
This keeps the domain free of HTTP, SQL, and vendor wire formats, and makes every
path testable with in-memory fakes.
"""
from __future__ import annotations

from typing import Protocol

from ..ledger.ledger import Posting
from ..ledger.money import Money
from .models import Transaction


class PaymentRail(Protocol):
    """Outbound money movement. Amounts cross as domain ``Money``; the adapter
    translates to the provider's wire format (minor units + currency)."""

    def request_collection(self, *, transfer_id: str, msisdn: str, amount: Money) -> None: ...

    def request_payout(self, *, transfer_id: str, msisdn: str, amount: Money) -> None: ...

    def request_refund(self, *, transfer_id: str) -> None: ...


class TransactionStore(Protocol):
    def get(self, transfer_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...


class LedgerPort(Protocol):
    def post(self, posting: Posting) -> None: ...
