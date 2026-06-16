"""Merchant-side charge (checkout) endpoints — behind the merchant password.

A merchant posts an amount → we create a ``Charge`` and hand back a QR encoding the customer
pay-page URL for that charge. The customer who scans it is charged exactly that amount
(server-derived, never client-set). A charge's status is *derived* from the payment it links to
(see ``domains.charges.models``), so the console can poll one endpoint and watch it go Paid.
"""
from __future__ import annotations

import io
import uuid

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..domains.charges.models import Charge, charge_status
from ..domains.ledger.money import Money
from .container import Container

charge_router = APIRouter()


class CreateChargeRequest(BaseModel):
    merchant_id: str
    amount: str  # major units, e.g. "12.50"


class ChargeResponse(BaseModel):
    id: str
    merchant_id: str
    merchant_name: str
    amount: str
    currency: str
    status: str  # awaiting_payment | processing | paid | declined | refunded | review
    transaction_id: str | None = None
    qr_svg_path: str


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _status_of(container: Container, charge: Charge) -> str:
    tx_state = None
    if charge.transaction_id is not None:
        try:
            tx_state = container.store.get(charge.transaction_id).state
        except KeyError:
            tx_state = None
    return charge_status(charge, tx_state)


def _response(container: Container, charge: Charge) -> ChargeResponse:
    merchant = container.merchants.get(charge.merchant_id)
    return ChargeResponse(
        id=charge.id,
        merchant_id=charge.merchant_id,
        merchant_name=merchant.name,
        amount=charge.amount.to_major_str(),
        currency=charge.amount.currency,
        status=_status_of(container, charge),
        transaction_id=charge.transaction_id,
        qr_svg_path=f"/charges/{charge.id}/qr.svg",
    )


@charge_router.post("/charges", response_model=ChargeResponse)
def create_charge(body: CreateChargeRequest, request: Request) -> ChargeResponse:
    """Create a charge for a posted amount. Returns the charge + the path to its QR."""
    container = _container(request)
    try:
        merchant = container.merchants.get(body.merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    if not merchant.is_active:
        raise HTTPException(status_code=422, detail="merchant is not active")
    try:
        amount = Money.from_major(body.amount, "USD")
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid amount: {exc}") from exc
    if not amount.is_positive:
        raise HTTPException(status_code=422, detail="amount must be positive")
    charge = Charge(id=uuid.uuid4().hex, merchant_id=merchant.id, amount=amount)
    container.charges.save(charge)
    return _response(container, charge)


@charge_router.get("/charges/{charge_id}", response_model=ChargeResponse)
def get_charge(charge_id: str, request: Request) -> ChargeResponse:
    """The charge's current state — the console polls this to watch it go Paid."""
    container = _container(request)
    try:
        charge = container.charges.get(charge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    return _response(container, charge)


@charge_router.get("/charges/{charge_id}/qr.svg")
def charge_qr(charge_id: str, request: Request) -> Response:
    """A scannable QR (printable SVG) encoding the customer pay page for this specific charge."""
    container = _container(request)
    try:
        container.charges.get(charge_id)  # validate it exists
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    pay_url = f"{request.base_url}customer/?charge={charge_id}"
    buff = io.BytesIO()
    segno.make(pay_url, error="m").save(buff, kind="svg", scale=6, border=2)
    return Response(content=buff.getvalue(), media_type="image/svg+xml")
