"""Pricing — what we charge to send.

Placeholder policy: a flat 1% of the amount, floored to the minor unit. Real pricing
(tiers, caps, CDF<->USD FX spread) is a later decision; isolating it here means the
orchestrator never hard-codes a fee.
"""
from __future__ import annotations

from ..ledger.money import Money

FEE_BASIS_POINTS = 100  # 1.00%


def default_fee(amount: Money) -> Money:
    return Money(amount.amount_minor * FEE_BASIS_POINTS // 10_000, amount.currency)
