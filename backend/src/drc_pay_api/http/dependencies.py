"""FastAPI dependency glue for the composition root.

The :class:`~drc_pay_api.container.Container` itself is framework-agnostic and lives at
package level (``drc_pay_api/container.py``) because every channel wires through it; this
module is the HTTP-only shim that hands it to routes via dependency injection.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request

from ..container import Container
from ..domains.merchants.models import Merchant
from ..domains.staff.models import ROLE_ADMIN, StaffPrincipal


def get_container(request: Request) -> Container:
    """The shared :class:`Container`, built once at startup and kept on ``app.state``."""
    container: Container = request.app.state.container
    return container


# FastAPI dependency: a route writes ``container: ContainerDep`` and FastAPI injects the shared
# container — replacing the per-file ``_container(request)`` helper that used to be copy-pasted.
ContainerDep = Annotated[Container, Depends(get_container)]


def get_current_merchant(
    container: ContainerDep,
    authorization: Annotated[str, Header()] = "",
    drcpay_session: Annotated[str, Cookie()] = "",
) -> Merchant:
    """The merchant behind the request's session — the authentication AND the
    authorization anchor: every merchant endpoint takes this and fences its data to the
    returned merchant. 401 (never 403) on any failure, without distinguishing missing /
    invalid / expired, so the response leaks nothing about token validity.

    Two session carriers, browser first:
    - the ``drcpay_session`` **HttpOnly cookie** — what the console relies on. The browser
      attaches it by itself, on EVERY page version: no JavaScript, no custom headers,
      nothing a browser quirk, an extension, or a stale cached page can break. (Hard-won:
      Safari replaces custom Authorization headers with cached HTTP Basic credentials from
      the sandbox demo gate, and browsers ran heuristically-cached old console code whose
      header protocol no longer matched the server.)
    - ``Authorization: Bearer`` — for curl and API clients, free of those quirks.
    """
    challenge = {"WWW-Authenticate": "Bearer"}
    token = (
        authorization[len("Bearer ") :] if authorization.startswith("Bearer ") else drcpay_session
    )
    if not token:
        raise HTTPException(status_code=401, detail="merchant login required", headers=challenge)
    merchant_id = container.auth.resolve(token)
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="session invalid or expired", headers=challenge)
    try:
        return container.merchants.get(merchant_id)
    except KeyError as exc:  # session for a deleted merchant — treat as unauthenticated
        raise HTTPException(
            status_code=401, detail="session invalid or expired", headers=challenge
        ) from exc


# A route writes ``merchant: CurrentMerchant`` — injecting the logged-in merchant and
# rejecting unauthenticated requests in one move.
CurrentMerchant = Annotated[Merchant, Depends(get_current_merchant)]


ADMIN_SESSION_COOKIE = "drcpay_admin_session"


def get_current_admin(
    container: ContainerDep,
    authorization: Annotated[str, Header()] = "",
    drcpay_admin_session: Annotated[str, Cookie()] = "",
) -> StaffPrincipal:
    """The staff member behind the request's admin session — the admin analogue of
    ``get_current_merchant``. 401 (never 403) on any auth failure, indistinguishably. A separate
    cookie (``drcpay_admin_session``) from the merchant console's, so being logged into one is
    never being logged into the other. Role/username are read fresh from the credential, so a
    role change or a deleted account takes effect immediately."""
    challenge = {"WWW-Authenticate": "Bearer"}
    token = (
        authorization[len("Bearer ") :]
        if authorization.startswith("Bearer ")
        else drcpay_admin_session
    )
    if not token:
        raise HTTPException(status_code=401, detail="admin login required", headers=challenge)
    staff_id = container.staff_auth.resolve(token)
    if staff_id is None:
        raise HTTPException(status_code=401, detail="session invalid or expired", headers=challenge)
    credential = container.staff_credentials.get_by_id(staff_id)
    if credential is None:  # session for a deleted staff account — treat as unauthenticated
        raise HTTPException(status_code=401, detail="session invalid or expired", headers=challenge)
    return StaffPrincipal(
        staff_id=credential.staff_id, username=credential.username, role=credential.role
    )


# A route writes ``admin: CurrentAdmin`` — injecting the logged-in staff member and rejecting
# unauthenticated requests in one move.
CurrentAdmin = Annotated[StaffPrincipal, Depends(get_current_admin)]


def require_admin(admin: StaffPrincipal) -> None:
    """Authorization on top of authentication: the staff member must hold the ``admin`` role.
    One role today, so this always passes — it is explicit so that adding a narrower role later
    (a read-only reviewer, say) doesn't silently grant approval or account-creation rights."""
    if admin.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="admin role required")
