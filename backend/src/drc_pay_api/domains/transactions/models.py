"""Transaction model — the workflow record for one cross-network transfer.

Note: this row is a *workflow tracker*, not the source of truth for money. The
ledger (``domains.ledger``) is the source of truth; this just tracks where a transfer
is in its lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger.money import Money
from .state_machine import TxState

# How a payment's outcome was established (its assurance level), recorded on the transaction.
RAIL_VERIFIED = (
    "rail_verified"  # pawaPay-settled, verified by the operator's RFC-9421 signed callback
)
MERCHANT_ATTESTED = (
    "merchant_attested"  # on-net: paid merchant-direct, the merchant confirmed receipt
)


@dataclass
class Transaction:
    id: str
    customer_msisdn: str  # the customer paying the merchant
    merchant_msisdn: str  # the merchant's settlement mobile-money number
    amount: Money  # the sticker price the customer pays
    fee: Money  # our charge (MDR); the merchant nets amount − fee, same currency
    state: TxState
    history: list[TxState] = field(default_factory=list)  # every state, in order
    idempotency_key: str | None = None  # client-supplied dedup key (stored; an API concern)
    merchant_id: str | None = None  # the registered merchant this payment is for
    # Resolved mobile-money operators (pawaPay provider codes). Captured at start so the
    # later, webhook-driven legs have them: the merchant's drives the settlement payout,
    # the customer's formats the refund amount to the right decimal precision.
    customer_provider: str | None = None
    merchant_provider: str | None = None
    # pawaPay operation ids (UUIDv4). Persisted so async callbacks correlate back to this
    # transaction and a refund can reference the original deposit.
    deposit_id: str | None = None
    payout_id: str | None = None
    refund_id: str | None = None
    # How the outcome is established (assurance level): RAIL_VERIFIED (pawaPay signed callback) or
    # MERCHANT_ATTESTED (on-net, the merchant confirmed they received it directly). See ADR 0009.
    provenance: str = RAIL_VERIFIED
