"""Merchant self-onboarding — the public sign-up endpoint.

``POST /signup`` lets a business register itself. It creates a **pending** merchant that
cannot log in or transact until an admin approves it (that approval surface is the staff/admin
side, added separately). Public by design — self-registration is the whole point — so input is
validated tightly here and the server, never the client, decides the merchant id, short-code,
and initial (pending) status.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..application import onboarding
from ..integrations.pawapay.providers import PROVIDER_DISPLAY_NAMES
from .dependencies import ContainerDep

onboarding_router = APIRouter()

# A DRC mobile-money number: 243 + 9 digits, optionally with a leading '+'. Normalised to the
# no-plus form the rest of the app stores (matches the seeded merchants, e.g. 243973456789).
_MSISDN_RE = re.compile(r"^\+?243\d{9}$")
# Login handle: 3–32 chars, letters/digits/._- (case-sensitive, as the credential store keys on it).
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
# A till/short-code is operator-issued digits; keep it lax but numeric and bounded.
_TILL_RE = re.compile(r"^\d{3,12}$")
_MIN_PASSWORD = 8
_MAX_NAME = 80


class SignupRequest(BaseModel):
    name: str
    settlement_msisdn: str
    settlement_provider: str | None = None  # pawaPay operator code; inferred later if omitted
    operator_till: str | None = None
    username: str
    password: str


class SignupResponse(BaseModel):
    merchant_id: str
    status: str  # always "pending" on success
    message: str


def _clean(value: str) -> str:
    return value.strip()


@onboarding_router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(body: SignupRequest, container: ContainerDep) -> SignupResponse:
    name = _clean(body.name)
    if not name or len(name) > _MAX_NAME:
        raise HTTPException(status_code=422, detail=f"name must be 1–{_MAX_NAME} characters")

    username = _clean(body.username)
    if not _USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=422,
            detail="username must be 3–32 characters (letters, digits, . _ -)",
        )

    if len(body.password) < _MIN_PASSWORD:
        raise HTTPException(
            status_code=422, detail=f"password must be at least {_MIN_PASSWORD} characters"
        )

    msisdn = _clean(body.settlement_msisdn)
    if not _MSISDN_RE.fullmatch(msisdn):
        raise HTTPException(
            status_code=422, detail="settlement number must be a DRC number, e.g. 243XXXXXXXXX"
        )
    msisdn = msisdn.lstrip("+")

    provider = _clean(body.settlement_provider) if body.settlement_provider else None
    if provider is not None and provider not in PROVIDER_DISPLAY_NAMES:
        raise HTTPException(status_code=422, detail=f"unknown settlement provider: {provider}")

    till = _clean(body.operator_till) if body.operator_till else None
    if till is not None and not _TILL_RE.fullmatch(till):
        raise HTTPException(status_code=422, detail="operator till must be 3–12 digits")

    try:
        merchant = onboarding.signup(
            merchants=container.merchants,
            credentials=container.credentials,
            name=name,
            settlement_msisdn=msisdn,
            settlement_provider=provider,
            operator_till=till,
            username=username,
            password=body.password,
        )
    except onboarding.UsernameTaken as exc:
        # 409, not 422: the request is well-formed, the username just isn't available.
        raise HTTPException(status_code=409, detail="username already taken") from exc

    return SignupResponse(
        merchant_id=merchant.id,
        status=merchant.status,
        message=(
            "Account created and pending approval. You'll be able to sign in once an "
            "administrator approves it."
        ),
    )
