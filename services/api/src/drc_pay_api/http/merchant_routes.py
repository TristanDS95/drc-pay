"""HTTP endpoints for merchants — list tills, serve each merchant's payment codes, and a
printable QR. The QR carries a `tel:` USSD dial-through, so a scan (Android) or a manual
dial both land in the `ussd/` channel pre-filled with the merchant's till.
"""
from __future__ import annotations

import io

import segno
from fastapi import APIRouter, HTTPException, Request, Response

from ..application.payment_codes import merchant_payment_code
from .container import Container
from .schemas import MerchantResponse

merchant_router = APIRouter()


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _merchant_response(container: Container, merchant_id: str) -> MerchantResponse:
    merchant = container.merchants.get(merchant_id)  # raises KeyError if missing
    code = merchant_payment_code(container.ussd_shortcode, merchant.short_code)
    return MerchantResponse(
        id=merchant.id,
        name=merchant.name,
        short_code=merchant.short_code,
        settlement_msisdn=merchant.settlement_msisdn,
        status=merchant.status,
        ussd_string=code.ussd_string,
        tel_uri=code.tel_uri,
        qr_svg_path=f"/merchants/{merchant.id}/qr.svg",
    )


@merchant_router.get("/merchants", response_model=list[MerchantResponse])
def list_merchants(request: Request) -> list[MerchantResponse]:
    container = _container(request)
    return [_merchant_response(container, merchant.id) for merchant in container.merchants.all()]


@merchant_router.get("/merchants/{merchant_id}", response_model=MerchantResponse)
def get_merchant(merchant_id: str, request: Request) -> MerchantResponse:
    container = _container(request)
    try:
        return _merchant_response(container, merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc


@merchant_router.get("/merchants/{merchant_id}/qr.svg")
def merchant_qr(merchant_id: str, request: Request) -> Response:
    """A scannable QR of the merchant's `tel:` USSD dial-through, as an SVG (printable)."""
    container = _container(request)
    try:
        merchant = container.merchants.get(merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    code = merchant_payment_code(container.ussd_shortcode, merchant.short_code)
    buff = io.BytesIO()
    segno.make(code.tel_uri, error="m").save(buff, kind="svg", scale=6, border=2)
    return Response(content=buff.getvalue(), media_type="image/svg+xml")
