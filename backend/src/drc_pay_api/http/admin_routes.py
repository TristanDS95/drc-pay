"""Staff (admin) login/logout/me — the session endpoints behind ``CurrentAdmin``.

The admin analogue of ``auth_routes``: a login exchanges username + password for a session,
``me`` echoes who the session belongs to, ``logout`` revokes. Same posture — indistinguishable
failures, an HttpOnly session cookie — but a **separate** cookie and service from the merchant
console, so the two identities never cross. The approve/reject endpoints that this login gates
live in the merchant-onboarding admin surface (added separately).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from pydantic import BaseModel

from ..application import staff_accounts
from ..domains.staff.models import ROLE_ADMIN
from ..domains.staff.service import SESSION_TTL
from .dependencies import ADMIN_SESSION_COOKIE, ContainerDep, CurrentAdmin, require_admin

admin_router = APIRouter()


def _set_admin_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminPrincipalResponse(BaseModel):
    staff_id: str
    username: str
    role: str


class AdminLoginResponse(BaseModel):
    token: str  # for Bearer-header clients; the browser gets the same token as an HttpOnly cookie
    admin: AdminPrincipalResponse


@admin_router.post("/admin/login", response_model=AdminLoginResponse)
def admin_login(
    body: AdminLoginRequest, request: Request, response: Response, container: ContainerDep
) -> AdminLoginResponse:
    token = container.staff_auth.login(body.username, body.password)
    if token is None:  # unknown user, wrong password, or throttled — indistinguishable
        raise HTTPException(status_code=401, detail="invalid username or password")
    credential = container.staff_credentials.get_by_username(body.username)
    if credential is None:  # deleted between verify and fetch — treat as a failed login
        raise HTTPException(status_code=401, detail="invalid username or password")
    _set_admin_cookie(response, token, secure=request.url.scheme == "https")
    return AdminLoginResponse(
        token=token,
        admin=AdminPrincipalResponse(
            staff_id=credential.staff_id, username=credential.username, role=credential.role
        ),
    )


@admin_router.get("/admin/me", response_model=AdminPrincipalResponse)
def admin_me(admin: CurrentAdmin) -> AdminPrincipalResponse:
    """Who the admin session belongs to — the admin page boots from this."""
    return AdminPrincipalResponse(staff_id=admin.staff_id, username=admin.username, role=admin.role)


class CreateStaffRequest(BaseModel):
    username: str
    password: str
    role: str = ROLE_ADMIN


@admin_router.get("/admin/staff", response_model=list[AdminPrincipalResponse])
def list_staff(admin: CurrentAdmin, container: ContainerDep) -> list[AdminPrincipalResponse]:
    """Who has staff access. Never returns password hashes."""
    require_admin(admin)
    return [
        AdminPrincipalResponse(staff_id=c.staff_id, username=c.username, role=c.role)
        for c in container.staff_credentials.all()
    ]


@admin_router.post("/admin/staff", response_model=AdminPrincipalResponse, status_code=201)
def create_staff(
    body: CreateStaffRequest, admin: CurrentAdmin, container: ContainerDep
) -> AdminPrincipalResponse:
    """An admin adds a colleague. Deliberately create-only: a taken username is a 409, never a
    silent password reset of an existing account (that would let one admin take over another's)."""
    require_admin(admin)
    try:
        credential = staff_accounts.create_staff(
            container.staff_credentials,
            username=body.username.strip(),
            password=body.password,
            role=body.role.strip(),
        )
    except staff_accounts.StaffUsernameTaken as exc:
        raise HTTPException(status_code=409, detail="username already taken") from exc
    except staff_accounts.InvalidStaffAccount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminPrincipalResponse(
        staff_id=credential.staff_id, username=credential.username, role=credential.role
    )


@admin_router.post("/admin/logout")
def admin_logout(
    response: Response,
    container: ContainerDep,
    authorization: Annotated[str, Header()] = "",
    drcpay_admin_session: Annotated[str, Cookie()] = "",
) -> dict[str, str]:
    """Revoke the presented admin session (either carrier) and clear the cookie. Idempotent."""
    token = (
        authorization[len("Bearer ") :]
        if authorization.startswith("Bearer ")
        else drcpay_admin_session
    )
    if token:
        container.staff_auth.logout(token)
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return {"status": "logged_out"}
