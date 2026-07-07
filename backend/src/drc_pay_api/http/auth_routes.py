"""Merchant login/logout — the session endpoints behind ``CurrentMerchant``.

The contract is deliberately small: ``login`` exchanges a username + password for an
opaque bearer token (the only moment it exists in plaintext), ``me`` echoes who the
token belongs to (the console boots from it), ``logout`` revokes. All failure modes
are indistinguishable 401s; the domain service (``domains/auth``) owns hashing,
expiry, and the login throttle.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .dependencies import ContainerDep, CurrentMerchant, session_token
from .merchant_api import merchant_profile
from .schemas import MerchantResponse

auth_router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str  # opaque bearer — the client sends it as ``Authorization: Bearer <token>``
    merchant: MerchantResponse


@auth_router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, container: ContainerDep) -> LoginResponse:
    token = container.auth.login(body.username, body.password)
    if token is None:  # unknown user, wrong password, or throttled — indistinguishable
        raise HTTPException(status_code=401, detail="invalid username or password")
    credential = container.credentials.get_by_username(body.username)
    assert credential is not None  # login just verified it
    return LoginResponse(token=token, merchant=merchant_profile(container, credential.merchant_id))


@auth_router.get("/auth/me", response_model=MerchantResponse)
def me(merchant: CurrentMerchant, container: ContainerDep) -> MerchantResponse:
    """Who the session belongs to — the console boots from this instead of listing merchants."""
    return merchant_profile(container, merchant.id)


@auth_router.post("/auth/logout")
def logout(
    container: ContainerDep,
    x_session_token: Annotated[str, Header()] = "",
    authorization: Annotated[str, Header()] = "",
) -> dict[str, str]:
    """Revoke the presented session (either carrier — see ``session_token``). Idempotent: an
    unknown/expired token is still a 200 — the caller's goal (this token no longer works) is
    met either way."""
    token = session_token(x_session_token, authorization)
    if token:
        container.auth.logout(token)
    return {"status": "logged_out"}
