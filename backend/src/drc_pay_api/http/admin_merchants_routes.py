"""The admin merchant-approval surface — list sign-ups and approve/reject them.

Admin-gated (``CurrentAdmin`` + the ``admin`` role): a staff member reviews self-onboarded
merchants and decides. Thin caller — it delegates the state change to ``application.onboarding``
(the same approve/reject used and tested in the onboarding domain) and serializes the result.
Distinct from ``admin_routes`` (which is only admin auth); both live under ``/admin``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..application import onboarding
from ..domains.merchants.models import STATUS_PENDING, Merchant
from ..domains.staff.models import ROLE_ADMIN, StaffPrincipal
from .dependencies import ContainerDep, CurrentAdmin

admin_merchants_router = APIRouter()

_STATUSES = {"pending", "active", "rejected", "suspended"}


class AdminMerchantResponse(BaseModel):
    id: str
    name: str
    short_code: str
    settlement_msisdn: str
    settlement_provider: str | None
    operator_till: str | None
    status: str


def _to_response(merchant: Merchant) -> AdminMerchantResponse:
    return AdminMerchantResponse(
        id=merchant.id,
        name=merchant.name,
        short_code=merchant.short_code,
        settlement_msisdn=merchant.settlement_msisdn,
        settlement_provider=merchant.settlement_provider,
        operator_till=merchant.operator_till,
        status=merchant.status,
    )


def _require_admin(admin: StaffPrincipal) -> None:
    # Only the admin role may act on merchant sign-ups. One role today, but the check is explicit
    # so adding a read-only or finer staff role later doesn't accidentally grant approval.
    if admin.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="admin role required")


@admin_merchants_router.get("/admin/merchants", response_model=list[AdminMerchantResponse])
def list_merchants(
    admin: CurrentAdmin, container: ContainerDep, status: str = STATUS_PENDING
) -> list[AdminMerchantResponse]:
    """Merchants for review, filtered by ``status`` (default ``pending`` — the approval worklist);
    pass ``status=all`` for every merchant."""
    _require_admin(admin)
    if status != "all" and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown status filter: {status}")
    merchants = container.merchants.all()
    if status != "all":
        merchants = [m for m in merchants if m.status == status]
    return [_to_response(m) for m in merchants]


@admin_merchants_router.post(
    "/admin/merchants/{merchant_id}/approve", response_model=AdminMerchantResponse
)
def approve_merchant(
    merchant_id: str, admin: CurrentAdmin, container: ContainerDep
) -> AdminMerchantResponse:
    """Activate a merchant so it can log in and transact. Idempotent."""
    _require_admin(admin)
    try:
        merchant = onboarding.approve(container.merchants, merchant_id)
    except onboarding.MerchantNotFound as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    return _to_response(merchant)


@admin_merchants_router.post(
    "/admin/merchants/{merchant_id}/reject", response_model=AdminMerchantResponse
)
def reject_merchant(
    merchant_id: str, admin: CurrentAdmin, container: ContainerDep
) -> AdminMerchantResponse:
    """Reject a merchant; it stays unable to log in or transact. Idempotent."""
    _require_admin(admin)
    try:
        merchant = onboarding.reject(container.merchants, merchant_id)
    except onboarding.MerchantNotFound as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    return _to_response(merchant)
