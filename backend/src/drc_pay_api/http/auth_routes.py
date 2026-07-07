"""Merchant login/logout — the session endpoints behind ``CurrentMerchant``.

The contract is deliberately small: a login exchanges username + password for a session,
``me`` echoes who the session belongs to (the console boots from it), ``logout`` revokes.
All failure modes are indistinguishable; the domain service (``domains/auth``) owns
hashing, expiry, and the login throttle.

Login has TWO transports, both ending in the same **HttpOnly session cookie**:

- ``POST /auth/login`` (JSON) — the console's fetch path; also returns the token for
  Bearer-header API clients.
- ``POST /auth/login-form`` (urlencoded) — a **plain HTML form target**: works with zero
  JavaScript. It exists because the login must not depend on anything a browser quirk,
  an extension, or a stale cached page can interfere with (this codebase has the Safari
  and cache scars to justify it). Parsed by hand so we don't grow a multipart dependency
  for two fields.

The cookie is the primary carrier: HttpOnly (no script can read it), SameSite=Strict
(cross-site pages can never ride it — the CSRF baseline for the cookie path), Secure on
HTTPS, and attached by the browser to every request from ANY page version — which is what
makes it immune to the header-protocol mismatches that stale cached pages caused.
"""
from __future__ import annotations

import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..domains.auth.service import SESSION_TTL
from .dependencies import ContainerDep, CurrentMerchant
from .merchant_api import merchant_profile
from .schemas import MerchantResponse

auth_router = APIRouter()

SESSION_COOKIE = "drcpay_session"


def _set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str  # for Bearer-header clients; the browser gets the same token as an HttpOnly cookie
    merchant: MerchantResponse


@auth_router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest, request: Request, response: Response, container: ContainerDep
) -> LoginResponse:
    token = container.auth.login(body.username, body.password)
    if token is None:  # unknown user, wrong password, or throttled — indistinguishable
        raise HTTPException(status_code=401, detail="invalid username or password")
    credential = container.credentials.get_by_username(body.username)
    assert credential is not None  # login just verified it
    _set_session_cookie(response, token, secure=request.url.scheme == "https")
    return LoginResponse(token=token, merchant=merchant_profile(container, credential.merchant_id))


@auth_router.post("/auth/login-form")
async def login_form(request: Request, container: ContainerDep) -> RedirectResponse:
    """The zero-JavaScript login: a native HTML form POST. Success → session cookie +
    redirect to the console; failure → redirect back with ``?login=failed`` (the page shows
    the error). 303 turns the POST into a GET on the redirect."""
    raw = (await request.body()).decode("utf-8", errors="replace")
    fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
    username = (fields.get("username") or [""])[0].strip()
    password = (fields.get("password") or [""])[0]
    token = container.auth.login(username, password)
    if token is None:
        return RedirectResponse("/console/?login=failed", status_code=303)
    response = RedirectResponse("/console/", status_code=303)
    _set_session_cookie(response, token, secure=request.url.scheme == "https")
    return response


@auth_router.get("/auth/me", response_model=MerchantResponse)
def me(merchant: CurrentMerchant, container: ContainerDep) -> MerchantResponse:
    """Who the session belongs to — the console boots from this instead of listing merchants."""
    return merchant_profile(container, merchant.id)


@auth_router.post("/auth/logout")
def logout(
    response: Response,
    container: ContainerDep,
    authorization: Annotated[str, Header()] = "",
    drcpay_session: Annotated[str, Cookie()] = "",
) -> dict[str, str]:
    """Revoke the presented session (either carrier) and clear the cookie. Idempotent: an
    unknown/expired token is still a 200 — the caller's goal (this session no longer
    works) is met either way."""
    token = (
        authorization[len("Bearer "):] if authorization.startswith("Bearer ") else drcpay_session
    )
    if token:
        container.auth.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "logged_out"}
