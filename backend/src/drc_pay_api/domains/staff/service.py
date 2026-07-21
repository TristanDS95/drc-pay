"""Staff (admin) authentication service — the admin analogue of ``domains/auth``.

Same design as merchant auth (Argon2id passwords, opaque server-side sessions with a fixed TTL,
an in-process login throttle, indistinguishable failures), kept as its own service so the
money-adjacent merchant auth is not touched. Framework-agnostic: routes hand in strings and get
back a staff id or ``None``.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .models import StaffCredential, StaffSession

SESSION_TTL = timedelta(hours=24)
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 60.0

_hasher = PasswordHasher()  # Argon2id, library defaults; verifies against the encoded hash's params


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class StaffCredentialStore(Protocol):
    def get_by_username(self, username: str) -> StaffCredential | None: ...

    def get_by_id(self, staff_id: str) -> StaffCredential | None: ...

    def save(self, credential: StaffCredential) -> None: ...

    def all(self) -> list[StaffCredential]: ...


class StaffSessionStore(Protocol):
    def get(self, token_hash: str) -> StaffSession | None: ...

    def save(self, session: StaffSession) -> None: ...

    def delete(self, token_hash: str) -> None: ...


class StaffAuthService:
    def __init__(self, credentials: StaffCredentialStore, sessions: StaffSessionStore) -> None:
        self._credentials = credentials
        self._sessions = sessions
        self._failures: dict[str, tuple[int, float]] = {}

    def login(self, username: str, password: str) -> str | None:
        """Verify the password and mint a session. Returns the bearer TOKEN or ``None`` —
        indistinguishably — for unknown user, wrong password, or a throttled username."""
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
            StaffSession(
                token_hash=_token_hash(token),
                staff_id=credential.staff_id,
                expires_at=datetime.now(UTC) + SESSION_TTL,
            )
        )
        return token

    def logout(self, token: str) -> None:
        self._sessions.delete(_token_hash(token))

    def resolve(self, token: str) -> str | None:
        """The staff id for a live session token, or ``None``. Expired sessions are treated as
        absent and lazily deleted."""
        session = self._sessions.get(_token_hash(token))
        if session is None:
            return None
        expires = session.expires_at
        if expires.tzinfo is None:  # SQLite (tests) returns naive datetimes; ours are UTC
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires:
            self._sessions.delete(session.token_hash)
            return None
        return session.staff_id

    # ---- login throttle (in-process brake, same posture as merchant auth) ----
    def _locked(self, username: str) -> bool:
        entry = self._failures.get(username)
        return entry is not None and entry[0] >= _MAX_FAILURES and time.monotonic() < entry[1]

    def _record_failure(self, username: str) -> None:
        count = self._failures.get(username, (0, 0.0))[0] + 1
        self._failures[username] = (count, time.monotonic() + _LOCKOUT_SECONDS)
