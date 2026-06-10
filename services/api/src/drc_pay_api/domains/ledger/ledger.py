"""Minimal double-entry ledger primitives.

The ledger — not the transaction row — is the source of truth for money. Every
movement is recorded as balanced debits and credits: for a given posting, the sum of
debits must equal the sum of credits, per currency. If they do not balance, we refuse
to post. This is the invariant that lets us prove, at any time, that the books are
correct.

This is a starter skeleton: it enforces the balancing invariant in memory. The
persistent, append-only implementation (Postgres, immutable rows) is built on top of
these types.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .money import Money


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True)
class Entry:
    """A single side of a posting: an amount moving into or out of an account."""

    account: str  # e.g. "payer:wallet", "payout:wallet", "revenue:fees"
    direction: Direction
    amount: Money


class UnbalancedPosting(ValueError):
    """Raised when a posting's debits and credits do not balance."""


@dataclass(frozen=True)
class Posting:
    """A group of entries recorded together (atomically). Must balance per currency."""

    transaction_id: str
    entries: tuple[Entry, ...]

    def __post_init__(self) -> None:
        if len(self.entries) < 2:
            raise UnbalancedPosting("a posting must have at least two entries")
        totals: dict[str, int] = {}
        for entry in self.entries:
            signed = (
                entry.amount.amount_minor
                if entry.direction is Direction.DEBIT
                else -entry.amount.amount_minor
            )
            totals[entry.amount.currency] = totals.get(entry.amount.currency, 0) + signed
        unbalanced = {cur: bal for cur, bal in totals.items() if bal != 0}
        if unbalanced:
            raise UnbalancedPosting(f"debits != credits: {unbalanced}")
