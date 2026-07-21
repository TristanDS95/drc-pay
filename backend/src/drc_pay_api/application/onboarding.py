"""Merchant self-onboarding — create a merchant + its login, and the approve/reject moves.

A merchant signs itself up (``signup``): we create a **pending** ``Merchant`` and its
``MerchantCredential`` (Argon2id-hashed password), generate a unique platform short-code, and
reject a username that is already taken. A pending merchant is inert — it cannot log in
(``AuthService`` gates on merchant status), take payments, or create charges (``is_active``
already fences those) — until an admin ``approve``s it (→ active) or ``reject``s it.

This moves no money and touches no ledger/state-machine code; it only writes the merchant and
credential stores. Channel- and framework-agnostic: the HTTP routes are thin callers.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from ..domains.auth.models import MerchantCredential
from ..domains.auth.service import hash_password
from ..domains.merchants.models import (
    STATUS_ACTIVE,
    STATUS_PENDING,
    STATUS_REJECTED,
    Merchant,
)


class MerchantStore(Protocol):
    def get(self, merchant_id: str) -> Merchant: ...

    def get_by_short_code(self, short_code: str) -> Merchant | None: ...

    def save(self, merchant: Merchant) -> None: ...

    def all(self) -> list[Merchant]: ...


class CredentialStore(Protocol):
    def get_by_username(self, username: str) -> MerchantCredential | None: ...

    def save(self, credential: MerchantCredential) -> None: ...


class UsernameTaken(Exception):
    """The requested login username already belongs to another merchant."""


class MerchantNotFound(Exception):
    """No merchant with the given id (for approve/reject)."""


def _next_short_code(merchants: MerchantStore) -> str:
    """The next free numeric short-code, one above the current maximum (min 1001), skipping any
    that are somehow already taken. Collision-checked against the store; the DB also enforces a
    unique constraint on ``short_code`` as the real guard."""
    numeric = [int(m.short_code) for m in merchants.all() if m.short_code.isdigit()]
    candidate = max(numeric, default=1000) + 1
    while merchants.get_by_short_code(str(candidate)) is not None:
        candidate += 1
    return str(candidate)


def signup(
    *,
    merchants: MerchantStore,
    credentials: CredentialStore,
    name: str,
    settlement_msisdn: str,
    settlement_provider: str | None,
    operator_till: str | None,
    username: str,
    password: str,
) -> Merchant:
    """Register a new merchant as **pending** and create its login. Raises ``UsernameTaken`` if
    the username is not free. The password is hashed (Argon2id) and never stored in the clear."""
    if credentials.get_by_username(username) is not None:
        raise UsernameTaken(username)
    merchant = Merchant(
        id="m_" + uuid.uuid4().hex[:12],
        name=name,
        short_code=_next_short_code(merchants),
        settlement_msisdn=settlement_msisdn,
        settlement_provider=settlement_provider,
        status=STATUS_PENDING,
        operator_till=operator_till,
    )
    merchants.save(merchant)
    credentials.save(
        MerchantCredential(
            merchant_id=merchant.id,
            username=username,
            password_hash=hash_password(password),
        )
    )
    return merchant


def approve(merchants: MerchantStore, merchant_id: str) -> Merchant:
    """Activate a pending merchant so it can log in and transact. Idempotent."""
    merchant = _require(merchants, merchant_id)
    merchant.status = STATUS_ACTIVE
    merchants.save(merchant)
    return merchant


def reject(merchants: MerchantStore, merchant_id: str) -> Merchant:
    """Mark a merchant rejected; it stays unable to log in or transact. Idempotent."""
    merchant = _require(merchants, merchant_id)
    merchant.status = STATUS_REJECTED
    merchants.save(merchant)
    return merchant


def pending(merchants: MerchantStore) -> list[Merchant]:
    """Every merchant awaiting an approval decision — the admin worklist."""
    return [m for m in merchants.all() if m.status == STATUS_PENDING]


def _require(merchants: MerchantStore, merchant_id: str) -> Merchant:
    try:
        return merchants.get(merchant_id)
    except KeyError as exc:
        raise MerchantNotFound(merchant_id) from exc
