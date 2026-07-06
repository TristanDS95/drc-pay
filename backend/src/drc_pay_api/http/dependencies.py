"""FastAPI dependency glue for the composition root.

The :class:`~drc_pay_api.container.Container` itself is framework-agnostic and lives at
package level (``drc_pay_api/container.py``) because every channel wires through it; this
module is the HTTP-only shim that hands it to routes via dependency injection.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from ..container import Container
from ..domains.merchants.models import Merchant


def get_container(request: Request) -> Container:
    """The shared :class:`Container`, built once at startup and kept on ``app.state``."""
    container: Container = request.app.state.container
    return container


# FastAPI dependency: a route writes ``container: ContainerDep`` and FastAPI injects the shared
# container — replacing the per-file ``_container(request)`` helper that used to be copy-pasted.
ContainerDep = Annotated[Container, Depends(get_container)]


def session_token(x_session_token: str, authorization: str) -> str:
    """The session token from a request, from either carrier:

    - ``X-Session-Token`` — the PRIMARY carrier, and the one the console uses. It exists
      because of a WebKit behavior: once a browser holds cached HTTP **Basic** credentials
      for an origin (the sandbox's demo-shell gate), Safari REPLACES any custom
      ``Authorization`` header on same-origin fetches with those Basic credentials — the
      Bearer token never reaches the server and every login appears to silently fail.
      A custom header is untouchable by that mechanism.
    - ``Authorization: Bearer`` — kept for API clients and curl, where no Basic
      credentials interfere.
    """
    if x_session_token:
        return x_session_token
    if authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return ""


def get_current_merchant(
    container: ContainerDep,
    x_session_token: Annotated[str, Header()] = "",
    authorization: Annotated[str, Header()] = "",
) -> Merchant:
    """The merchant behind the request's session token — the authentication AND the
    authorization anchor: every merchant endpoint takes this and fences its data to the
    returned merchant. 401 (never 403) on any failure, without distinguishing missing /
    invalid / expired, so the response leaks nothing about token validity."""
    challenge = {"WWW-Authenticate": "Bearer"}
    token = session_token(x_session_token, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="merchant login required", headers=challenge)
    merchant_id = container.auth.resolve(token)
    if merchant_id is None:
        raise HTTPException(
            status_code=401, detail="session invalid or expired", headers=challenge
        )
    try:
        return container.merchants.get(merchant_id)
    except KeyError as exc:  # session for a deleted merchant — treat as unauthenticated
        raise HTTPException(
            status_code=401, detail="session invalid or expired", headers=challenge
        ) from exc


# A route writes ``merchant: CurrentMerchant`` — injecting the logged-in merchant and
# rejecting unauthenticated requests in one move.
CurrentMerchant = Annotated[Merchant, Depends(get_current_merchant)]
