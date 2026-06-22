"""Merchant — a registered business that accepts payments through the platform.

The merchant is the *payee* side of every transaction: a customer pays a merchant, and
the collected funds settle to the merchant's mobile-money account. This is a lightweight
MVP record — identity, where to settle, and the till code a customer references (e.g. via
USSD). Full onboarding / KYC is a separate, flagged concern.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Merchant:
    id: str
    name: str
    short_code: str  # the till / merchant code a customer enters (e.g. via USSD)
    settlement_msisdn: str  # mobile-money number that receives settlement payouts
    settlement_provider: str | None = None  # pawaPay operator code; resolved if omitted
    status: str = "active"  # active | suspended

    @property
    def is_active(self) -> bool:
        return self.status == "active"
