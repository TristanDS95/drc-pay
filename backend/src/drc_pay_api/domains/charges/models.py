"""A Charge — a merchant's request for a specific payment (a checkout / bill).

The merchant posts an amount; a QR carries the charge id; the customer who scans it is charged
exactly that amount (server-authoritative — never the client). The charge's **status is derived
from the payment it links to** — the transaction is the single source of truth, so we never keep
a separate status field that could drift out of sync.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger.money import Money
from ..transactions.state_machine import TxState

# Charge display statuses (derived, not stored).
AWAITING_PAYMENT = "awaiting_payment"  # created, nobody has paid it yet
PROCESSING = "processing"  # a payment is in flight (collecting / settling)
PAID = "paid"  # settled to the merchant
DECLINED = "declined"  # the collection failed — the charge is open to pay again
REFUNDED = "refunded"  # collected then settlement failed → customer refunded
REVIEW = "review"  # stuck; needs a human

# Map the linked transaction's terminal/in-flight state to a charge status. Anything not listed
# (the in-flight states) is "processing".
_FROM_TX_STATE: dict[TxState, str] = {
    TxState.PAYOUT_SUCCEEDED: PAID,
    TxState.COLLECTION_FAILED: DECLINED,
    TxState.REFUNDED: REFUNDED,
    TxState.MANUAL_REVIEW: REVIEW,
}


@dataclass
class Charge:
    id: str
    merchant_id: str
    amount: Money
    transaction_id: str | None = None  # the payment that fulfilled it, once a customer pays


def charge_status(charge: Charge, tx_state: TxState | None) -> str:
    """Derive a charge's display status from its linked transaction's state."""
    if charge.transaction_id is None or tx_state is None:
        return AWAITING_PAYMENT
    return _FROM_TX_STATE.get(tx_state, PROCESSING)


def is_payable(charge: Charge, tx_state: TxState | None) -> bool:
    """A charge can (still) be paid if nothing has claimed it yet, or the only attempt declined
    at collection (no money moved) — so a customer can retry. A paid/processing charge is closed."""
    return charge.transaction_id is None or tx_state is TxState.COLLECTION_FAILED
