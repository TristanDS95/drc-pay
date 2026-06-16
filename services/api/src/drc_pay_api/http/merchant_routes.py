"""HTTP endpoints for merchants — list tills and serve each merchant's payment codes (the USSD
string / tel URI). Scan-to-pay QRs are per-charge now (see ``charge_routes``), not per-merchant.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

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
