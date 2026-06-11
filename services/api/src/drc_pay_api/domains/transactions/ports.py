"""Ports — the interfaces the orchestrator depends on (ports-and-adapters).

The orchestrator talks only to these abstractions, never to concrete infrastructure.
The real adapters live elsewhere:
  - ``PaymentRail``      -> the pawaPay client in ``integrations.pawapay`` (and the
                            in-process ``SimulatedPaymentRail`` for dev/tests)
  - ``TransactionStore`` -> a Postgres-backed repository
  - ``LedgerPort``       -> the append-only double-entry ledger
  - ``Recorder``         -> an optional observability sink (used to surface a trace)
This keeps the domain free of HTTP, SQL, and vendor wire formats, and makes every path
testable with in-memory adapters.
"""
from __future__ import annotations

from typing import Protocol

from ..ledger.ledger import Posting
from ..ledger.money import Money
from .models import Transaction


class PaymentRail(Protocol):
    """Outbound money movement. Amounts cross as domain ``Money``; the adapter
    translates to the provider's wire format (minor units + currency)."""

    def request_collection(self, *, transaction_id: str, msisdn: str, amount: Money) -> None: ...

    def request_payout(self, *, transaction_id: str, msisdn: str, amount: Money) -> None: ...

    def request_refund(self, *, transaction_id: str) -> None: ...


class TransactionStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...


class LedgerPort(Protocol):
    def post(self, posting: Posting) -> None: ...


class Recorder(Protocol):
    """Observability port. If supplied to the orchestrator, each step (validation,
    state transition, rail call, ledger posting) is narrated here as a human-readable
    line — handy for surfacing an operations trace. Optional: omit for silence."""

    def record(self, message: str) -> None: ...
