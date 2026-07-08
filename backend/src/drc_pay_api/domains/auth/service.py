"""Merchant authentication service — password verification and session lifecycle.

Framework-agnostic (no HTTP knowledge): the routes hand in strings and get back a
merchant id or ``None``. Design choices, per the security roadmap:

- **Argon2id** for password hashing (the documented standard for this codebase) with
  library defaults; verification is constant-time inside argon2.
- **Opaque server-side sessions**: login mints a ``secrets.token_urlsafe`` bearer token,
  we persist only its SHA-256 with a fixed TTL. Opaque + server-side means revocation is
  a row delete and a leaked DB replays nothing (vs. signed tokens, which can't be
  revoked without extra machinery this app doesn't need yet).
- **A small in-process login throttle**: after ``_MAX_FAILURES`` consecutive failures a
  username is locked for ``_LOCKOUT_SECONDS``. This is a brake, not the real rate
  limiter (that is a separate Gate A item and needs shared state once multi-instance);
  it stops naive online guessing on the single-container deploys we run today.
- Passwords and tokens are **never logged** and never stored; failure reasons are not
  distinguished to the caller (unknown user == wrong password).
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .models import MerchantCredential, MerchantSession

SESSION_TTL = timedelta(hours=24)
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 60.0

_hasher = PasswordHasher()  # Argon2id, library defaults (time=3, 64 MiB, parallelism=4)


def hash_password(password: str) -> str:
    """Argon2id-encode a password for storage. Used by the seeder / future onboarding."""
    return _hasher.hash(password)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class CredentialStore(Protocol):
    def get_by_username(self, username: str) -> MerchantCredential | None: ...

    def save(self, credential: MerchantCredential) -> None: ...


class SessionStore(Protocol):
    def get(self, token_hash: str) -> MerchantSession | None: ...

    def save(self, session: MerchantSession) -> None: ...

    def delete(self, token_hash: str) -> None: ...


class AuthService:
    def __init__(self, credentials: CredentialStore, sessions: SessionStore) -> None:
        self._credentials = credentials
        self._sessions = sessions
        # username -> (consecutive failures, lockout-until monotonic timestamp)
        self._failures: dict[str, tuple[int, float]] = {}

    # ---- login / logout ------------------------------------------------------
    def login(self, username: str, password: str) -> str | None:
        """Verify the password and mint a session. Returns the bearer TOKEN (the only time
        it exists in plaintext) or ``None`` — indistinguishably — for unknown user, wrong
        password, or a throttled username."""
        if self._locked(username):
            return None
        credential = self._credentials.get_by_username(username)
        if credential is None:
            self._record_failure(username)
            return None
        try:
            _hasher.verify(credential.password_hash, password)
        except (VerifyMismatchError, VerificationError):
            self._record_failure(username)
            return None
        self._failures.pop(username, None)
        token = secrets.token_urlsafe(32)
        self._sessions.save(
            MerchantSession(
                token_hash=_token_hash(token),
                merchant_id=credential.merchant_id,
                expires_at=datetime.now(UTC) + SESSION_TTL,
            )
        )
        return token

    def logout(self, token: str) -> None:
        self._sessions.delete(_token_hash(token))

    def resolve(self, token: str) -> str | None:
        """The merchant id for a live session token, or ``None``. Expired sessions are
        treated as absent and lazily deleted."""
        session = self._sessions.get(_token_hash(token))
        if session is None:
            return None
        # SQLite (tests) returns naive datetimes; ours are always stored as UTC.
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires:
            self._sessions.delete(session.token_hash)
            return None
        return session.merchant_id

    # ---- login throttle (in-process brake, not the real rate limiter) --------
    def _locked(self, username: str) -> bool:
        entry = self._failures.get(username)
        return entry is not None and entry[0] >= _MAX_FAILURES and time.monotonic() < entry[1]

    def _record_failure(self, username: str) -> None:
        count = self._failures.get(username, (0, 0.0))[0] + 1
        self._failures[username] = (count, time.monotonic() + _LOCKOUT_SECONDS)
