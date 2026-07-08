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


class RailRejected(Exception):
    """Raised by a ``PaymentRail`` when the provider *synchronously* rejects a request
    (rather than accepting it for asynchronous processing). The orchestrator maps this to
    an immediate failure of that leg — it will not wait for a callback that never comes."""


class DuplicateIdempotencyKey(Exception):
    """Raised by a ``TransactionStore`` when a ``save`` would create a *second*, distinct
    transaction under an idempotency key already held by another. It is the storage layer's
    atomic guarantee against a double charge when two money-moving requests with the same key
    race past a pre-check. The application layer catches it and returns the original."""


class PaymentRail(Protocol):
    """Outbound money movement. Amounts cross as domain ``Money``; the adapter
    translates to the provider's wire format (minor units + currency). ``provider`` is
    the pawaPay operator code for the wallet being charged or paid.

    Each call returns the provider's operation id (or ``None`` for rails that issue
    none, e.g. the simulator). The orchestrator persists it so a later async callback
    can correlate back to the transaction, and so a refund can reference the original
    deposit. The call is only the *request*: the final outcome arrives asynchronously
    via the ``on_*_result`` handlers. A *synchronous* rejection raises ``RailRejected``."""

    def request_collection(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None: ...

    def request_payout(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None: ...

    def request_refund(
        self, *, transaction_id: str, deposit_id: str | None, amount: Money, provider: str
    ) -> str | None: ...


class TransactionStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...


class IdempotentTransactionStore(TransactionStore, Protocol):
    """A ``TransactionStore`` that can also be queried by idempotency key. Kept separate so the
    write-only paths (the orchestrator, the reconciliation applier) require only ``get``/``save``,
    while the entry point that must dedup money-moving requests asks for this wider contract."""

    def find_by_idempotency_key(self, key: str) -> Transaction | None: ...


class LedgerPort(Protocol):
    def post(self, posting: Posting) -> None: ...


class Recorder(Protocol):
    """Observability port. If supplied to the orchestrator, each step (validation,
    state transition, rail call, ledger posting) is narrated here as a human-readable
    line — handy for surfacing an operations trace. Optional: omit for silence."""

    def record(self, message: str) -> None: ...
