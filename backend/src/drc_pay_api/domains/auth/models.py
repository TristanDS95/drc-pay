"""Merchant authentication records — who a merchant is (credential) and who is currently
logged in (session).

Pure data; hashing and verification live in ``service.py``. Two hard rules, enforced by
construction rather than discipline:

- **No plaintext secrets at rest.** A credential stores only the Argon2id hash of the
  password; a session stores only the SHA-256 of its bearer token. Neither the password
  nor the token can be recovered from what we persist — a leaked database leaks nothing
  a client can replay.
- **Sessions expire.** A session carries its own ``expires_at``; resolution treats an
  expired row as absent (and deletes it lazily).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MerchantCredential:
    """A merchant's login: the username they type and the Argon2id hash of their password."""

    merchant_id: str
    username: str  # unique, case-sensitive; the login handle (demo: alpha/beta/gamma)
    password_hash: str  # Argon2id encoded hash — never the password itself


@dataclass
class MerchantSession:
    """A logged-in merchant. The client holds the opaque bearer token; we hold only its
    SHA-256, so a database read can never mint a valid Authorization header."""

    token_hash: str  # SHA-256 hex of the bearer token
    merchant_id: str
    expires_at: datetime  # timezone-aware UTC; expiry is checked in service.resolve()
