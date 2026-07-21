"""Creating staff (admin) accounts — one place, three callers.

Staff accounts arrive three ways, and they want subtly different semantics:

- **Bootstrap** (``DRCPAY_ADMIN_USERNAME``/``_PASSWORD`` at deploy) and the **CLI** use
  :func:`upsert_staff`: create-or-update by username, so a redeploy rotates that account's
  password instead of creating a duplicate.
- The **admin endpoint** (an admin adding a colleague) uses :func:`create_staff`, which refuses
  an existing username. Silently updating there would let one admin reset another's password by
  guessing their username — a privilege problem, not a convenience.

Validation is shared so every path enforces the same shape. Passwords are Argon2id-hashed here
and never stored or returned in the clear.
"""

from __future__ import annotations

import re
from typing import Protocol
from uuid import uuid4

from ..domains.auth.service import hash_password
from ..domains.staff.models import ROLE_ADMIN, StaffCredential

# Same shape as the merchant sign-up handle: 3–32 chars, letters/digits/._- (case-sensitive).
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
MIN_PASSWORD = 8
ROLES = {ROLE_ADMIN}


# Two protocols, not one: creating an account needs only lookup+save, so callers that can only do
# that (the deploy-time bootstrap) aren't forced to implement deletion they never perform.
class StaffCredentialStore(Protocol):
    def get_by_username(self, username: str) -> StaffCredential | None: ...

    def save(self, credential: StaffCredential) -> None: ...


class StaffCredentialAdminStore(StaffCredentialStore, Protocol):
    """Additionally supports removal — needed to delete an account safely (and to count the
    remaining ones, so the last account can't be removed)."""

    def all(self) -> list[StaffCredential]: ...

    def delete(self, staff_id: str) -> None: ...


class StaffSessionStore(Protocol):
    def delete_for_staff(self, staff_id: str) -> int: ...


class StaffNotFound(Exception):
    """No staff account with that username."""


class LastStaffAccount(Exception):
    """Refusing to remove the only remaining staff account — that would lock everyone out."""


class InvalidStaffAccount(ValueError):
    """The requested username/password/role is not acceptable."""


class StaffUsernameTaken(Exception):
    """A staff account with that username already exists."""


def validate(username: str, password: str, role: str) -> None:
    """Raise :class:`InvalidStaffAccount` unless the account details are acceptable."""
    if not _USERNAME_RE.fullmatch(username):
        raise InvalidStaffAccount("username must be 3-32 characters (letters, digits, . _ -)")
    if len(password) < MIN_PASSWORD:
        raise InvalidStaffAccount(f"password must be at least {MIN_PASSWORD} characters")
    if role not in ROLES:
        raise InvalidStaffAccount(f"unknown role: {role}")


def create_staff(
    store: StaffCredentialStore, *, username: str, password: str, role: str = ROLE_ADMIN
) -> StaffCredential:
    """Create a NEW staff account. Raises :class:`StaffUsernameTaken` if the username exists —
    this path must never overwrite another admin's credentials."""
    validate(username, password, role)
    if store.get_by_username(username) is not None:
        raise StaffUsernameTaken(username)
    credential = StaffCredential(
        staff_id=f"s_{uuid4().hex[:12]}",
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    store.save(credential)
    return credential


def remove_staff(
    store: StaffCredentialAdminStore, sessions: StaffSessionStore, *, username: str
) -> int:
    """Delete a staff account and revoke its live sessions, returning how many were revoked.

    Sessions go first: ``staff_sessions.staff_id`` is a foreign key to the credential, so the
    delete would be rejected otherwise (and a still-valid session for a deleted account would be
    a security hole in its own right).

    Refuses to remove the LAST staff account — deleting it would leave nobody able to sign in and
    no way back in short of database surgery.
    """
    credential = store.get_by_username(username)
    if credential is None:
        raise StaffNotFound(username)
    if len(store.all()) <= 1:
        raise LastStaffAccount(username)
    revoked = sessions.delete_for_staff(credential.staff_id)
    store.delete(credential.staff_id)
    return revoked


def upsert_staff(
    store: StaffCredentialStore, *, username: str, password: str, role: str = ROLE_ADMIN
) -> StaffCredential:
    """Create the account, or update the existing one's password/role in place (keeping its
    ``staff_id``). Idempotent — this is what makes rotating the bootstrap password on redeploy
    work without piling up duplicate accounts."""
    validate(username, password, role)
    existing = store.get_by_username(username)
    credential = StaffCredential(
        staff_id=existing.staff_id if existing is not None else f"s_{uuid4().hex[:12]}",
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    store.save(credential)
    return credential
