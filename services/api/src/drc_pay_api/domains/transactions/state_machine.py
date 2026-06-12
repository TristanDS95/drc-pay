"""The transaction state machine.

A payment is two legs — collect from the customer's wallet, then settle to the
merchant's — with an automatic refund if the settlement fails after the collection
already succeeded. We model that as an explicit finite-state machine so that (a) only
legal transitions are possible, and (b) money can never be "half moved" without a
recorded reason. Illegal transitions raise: they are bugs, not edge cases to paper
over.
"""
from __future__ import annotations

from enum import Enum


class TxState(str, Enum):
    INITIATED = "initiated"
    COLLECTION_PENDING = "collection_pending"
    COLLECTION_SUCCEEDED = "collection_succeeded"
    COLLECTION_FAILED = "collection_failed"  # terminal — nothing was taken
    PAYOUT_PENDING = "payout_pending"
    PAYOUT_SUCCEEDED = "payout_succeeded"  # terminal — success
    PAYOUT_FAILED = "payout_failed"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"  # terminal — money returned to customer
    MANUAL_REVIEW = "manual_review"  # needs a human; NOT terminal


# Allowed transitions. Anything not listed here is illegal by construction.
_TRANSITIONS: dict[TxState, frozenset[TxState]] = {
    TxState.INITIATED: frozenset({TxState.COLLECTION_PENDING, TxState.MANUAL_REVIEW}),
    TxState.COLLECTION_PENDING: frozenset(
        {TxState.COLLECTION_SUCCEEDED, TxState.COLLECTION_FAILED, TxState.MANUAL_REVIEW}
    ),
    TxState.COLLECTION_SUCCEEDED: frozenset({TxState.PAYOUT_PENDING, TxState.MANUAL_REVIEW}),
    TxState.COLLECTION_FAILED: frozenset(),  # terminal
    TxState.PAYOUT_PENDING: frozenset(
        {TxState.PAYOUT_SUCCEEDED, TxState.PAYOUT_FAILED, TxState.MANUAL_REVIEW}
    ),
    TxState.PAYOUT_SUCCEEDED: frozenset(),  # terminal
    TxState.PAYOUT_FAILED: frozenset({TxState.REFUND_PENDING, TxState.MANUAL_REVIEW}),
    TxState.REFUND_PENDING: frozenset({TxState.REFUNDED, TxState.MANUAL_REVIEW}),
    TxState.REFUNDED: frozenset(),  # terminal
    # A human resolves a review by pushing it back onto a normal path.
    TxState.MANUAL_REVIEW: frozenset(
        {
            TxState.PAYOUT_PENDING,
            TxState.REFUND_PENDING,
            TxState.REFUNDED,
            TxState.COLLECTION_FAILED,
        }
    ),
}

TERMINAL_STATES: frozenset[TxState] = frozenset(
    state for state, nxt in _TRANSITIONS.items() if not nxt
)


class IllegalTransition(Exception):
    """Raised when code attempts a transition the machine does not allow."""

    def __init__(self, src: TxState, dst: TxState) -> None:
        super().__init__(f"illegal transition: {src.value} -> {dst.value}")
        self.src = src
        self.dst = dst


def can_transition(src: TxState, dst: TxState) -> bool:
    return dst in _TRANSITIONS[src]


def assert_transition(src: TxState, dst: TxState) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(src, dst)


def is_terminal(state: TxState) -> bool:
    return state in TERMINAL_STATES
