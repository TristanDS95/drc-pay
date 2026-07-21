"""Staff (admin) identity — who a platform operator is (credential, with a role) and who is
currently logged in (session).

Deliberately a **separate** domain from merchant auth, not a generalisation of it: the merchant
auth path is money-adjacent and stays untouched. Same two hard rules apply here, by construction:

- **No plaintext secrets at rest.** A credential stores only the Argon2id hash of the password;
  a session stores only the SHA-256 of its bearer token.
- **Sessions expire.** A session carries its own ``expires_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# The only staff role today: may review and approve/reject merchant sign-ups. Kept as a field
# (not a boolean) so finer roles can be added later without a schema change.
ROLE_ADMIN = "admin"


@dataclass
class StaffCredential:
    """A staff member's login and what they're allowed to do."""

    staff_id: str
    username: str  # unique, case-sensitive login handle
    password_hash: str  # Argon2id encoded hash — never the password itself
    role: str = ROLE_ADMIN


@dataclass
class StaffSession:
    """A logged-in staff member. The client holds the opaque bearer token; we hold only its
    SHA-256. Minimal by design (id + expiry) — role and username are read fresh from the
    credential on each request, so a role change takes effect without re-login."""

    token_hash: str  # SHA-256 hex of the bearer token
    staff_id: str
    expires_at: datetime  # timezone-aware UTC


@dataclass
class StaffPrincipal:
    """The authenticated staff member a request resolves to — the admin analogue of
    ``CurrentMerchant``. Carries the role so endpoints can authorize on it."""

    staff_id: str
    username: str
    role: str
