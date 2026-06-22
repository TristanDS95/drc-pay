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


class DirectCollectRail(Protocol):
    """On-net (same-network) money movement — used when the payer and merchant share an operator.
    ONE operation: collect from the customer's wallet straight to the merchant's, on the operator's
    own network (a direct C2B), with no payout leg and no custody by us. ``provider`` is the shared
    operator code both sides are on.

    Returns the operator's operation id (or ``None`` for rails that issue none, e.g. the simulator).
    The call is only the *request*: the final outcome arrives asynchronously via the operator's
    confirmation callback → ``OnNetOrchestrator.on_confirm``. A *synchronous* rejection raises
    ``RailRejected``. The real adapters live in ``integrations.mpesa`` / ``integrations.airtel``."""

    def request_direct_collection(
        self,
        *,
        transaction_id: str,
        payer_msisdn: str,
        merchant_msisdn: str,
        amount: Money,
        provider: str,
    ) -> str | None: ...


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
