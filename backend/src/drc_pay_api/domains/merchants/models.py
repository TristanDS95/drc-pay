"""Merchant — a registered business that accepts payments through the platform.

The merchant is the *payee* side of every transaction: a customer pays a merchant, and
the collected funds settle to the merchant's mobile-money account. This is a lightweight
MVP record — identity, where to settle, and the till code a customer references (e.g. via
USSD). Full onboarding / KYC is a separate, flagged concern.
"""

from __future__ import annotations

from dataclasses import dataclass

# Merchant lifecycle. A self-onboarded merchant starts PENDING and is inert (cannot log in,
# take payments, or create charges) until an admin flips it to ACTIVE; REJECTED and SUSPENDED
# are the two other non-active terminal/holding states. Only ACTIVE transacts.
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
STATUS_SUSPENDED = "suspended"


@dataclass
class Merchant:
    id: str
    name: str
    short_code: (
        str  # the DRC Pay platform code a customer enters (e.g. via USSD: *123*<short_code>#)
    )
    settlement_msisdn: str  # mobile-money number that receives settlement payouts
    settlement_provider: str | None = None  # pawaPay operator code; resolved if omitted
    status: str = STATUS_ACTIVE  # pending | active | rejected | suspended
    # The merchant's OWN operator "buy goods" till on their settlement network — what an on-net
    # (same-network) customer pays directly. Preferred over ``settlement_msisdn`` for the on-net
    # hand-off: it shows the business name and is the path operators can later auto-notify us on.
    # Optional — merchants without a till fall back to send-to-number (P2P). See ADR 0009.
    operator_till: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE
