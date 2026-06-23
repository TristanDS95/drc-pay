"""The merchant-facing HTTP API — every endpoint here is behind the merchant password (one
trust tier), which is why they live in one file.

Consolidates what were three modules (transactions, merchants, charges): they share an audience
(the authenticated merchant console) and a change cadence, so they belong together. Each handler
is a thin caller — it takes the shared ``Container`` via ``ContainerDep``, validates input,
delegates to an ``application/`` service, and serializes the result. No money logic lives here.

Sections below: transactions (the demo/core payment), merchants (read-only tills), charges
(the scan-to-pay checkout).
"""
from __future__ import annotations

import io
import uuid

import segno
from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

from ..adapters.memory import ListRecorder
from ..application.payment_codes import merchant_payment_code
from ..application.payments import start_merchant_payment
from ..domains.charges.models import Charge, charge_status
from ..domains.ledger.money import Money
from ..domains.transactions.models import Transaction
from .container import Container, ContainerDep
from .schemas import (
    CreateTransactionRequest,
    LedgerLine,
    MerchantResponse,
    TransactionResponse,
)

merchant_api_router = APIRouter()


# ---- transactions -----------------------------------------------------------
_SCENARIOS = {"success", "payout_fail", "collection_fail", "refund_fail"}


def _merchant_name(container: Container, merchant_id: str | None) -> str | None:
    if not merchant_id:
        return None
    try:
        return container.merchants.get(merchant_id).name
    except KeyError:
        return None


def _to_response(
    container: Container, transaction: Transaction, trace: list[str]
) -> TransactionResponse:
    lines = [
        LedgerLine(
            account=entry.account,
            direction=entry.direction.value,
            amount=entry.amount.to_major_str(),
            currency=entry.amount.currency,
        )
        for posting in container.ledger.for_transaction(transaction.id)
        for entry in posting.entries
    ]
    return TransactionResponse(
        id=transaction.id,
        customer_msisdn=transaction.customer_msisdn,
        merchant_id=transaction.merchant_id,
        merchant_name=_merchant_name(container, transaction.merchant_id),
        merchant_msisdn=transaction.merchant_msisdn,
        amount=transaction.amount.to_major_str(),
        fee=transaction.fee.to_major_str(),
        currency=transaction.amount.currency,
        state=transaction.state.value,
        history=[s.value for s in transaction.history],
        ledger=lines,
        customer_provider=transaction.customer_provider,
        merchant_provider=transaction.merchant_provider,
        deposit_id=transaction.deposit_id,
        payout_id=transaction.payout_id,
        refund_id=transaction.refund_id,
        trace=trace,
    )


@merchant_api_router.post("/transactions", response_model=TransactionResponse)
def create_transaction(
    body: CreateTransactionRequest,
    container: ContainerDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TransactionResponse:
    if body.scenario not in _SCENARIOS:
        raise HTTPException(status_code=422, detail=f"unknown scenario: {body.scenario}")
    try:
        amount = Money.from_major(body.amount, body.currency)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid amount/currency: {exc}") from exc
    if not amount.is_positive:
        raise HTTPException(status_code=422, detail="amount must be positive")

    # Resolve the merchant being paid (server-derived settlement — never trust the client).
    try:
        merchant = container.merchants.get(body.merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    if not merchant.is_active:
        raise HTTPException(status_code=422, detail="merchant is not active")

    # Idempotency: a repeated key returns the ORIGINAL result, never a second charge.
    if idempotency_key is not None:
        existing = container.store.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _to_response(
                container, existing, ["idempotent replay · key already processed; original returned"]
            )

    recorder = ListRecorder()
    recorder.record(f"POST /transactions · {body.amount} {body.currency} · scenario={body.scenario}")
    recorder.record(f"merchant · {merchant.name} ({merchant.id}) · settle → {merchant.settlement_msisdn}")
    if body.defer:
        recorder.record("demo · deferring outcome — payment stays pending until reconciled")

    transaction_id = start_merchant_payment(
        store=container.store,
        ledger=container.ledger,
        rail=container.rail,
        predictor=container.predictor,
        simulated=container.simulated,
        customer_msisdn=body.customer_msisdn,
        merchant=merchant,
        amount=amount,
        customer_provider_override=body.customer_provider,
        idempotency_key=idempotency_key,
        scenario=body.scenario,
        defer=body.defer,
        recorder=recorder,
    )
    return _to_response(container, container.store.get(transaction_id), recorder.messages)


@merchant_api_router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: str, container: ContainerDep) -> TransactionResponse:
    try:
        transaction = container.store.get(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return _to_response(container, transaction, [])


@merchant_api_router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(container: ContainerDep) -> list[TransactionResponse]:
    return [_to_response(container, tx, []) for tx in container.store.all()]


# ---- merchants --------------------------------------------------------------
def _merchant_response(container: Container, merchant_id: str) -> MerchantResponse:
    merchant = container.merchants.get(merchant_id)  # raises KeyError if missing
    code = merchant_payment_code(container.ussd_shortcode, merchant.short_code)
    return MerchantResponse(
        id=merchant.id,
        name=merchant.name,
        short_code=merchant.short_code,
        settlement_msisdn=merchant.settlement_msisdn,
        settlement_provider=merchant.settlement_provider,
        status=merchant.status,
        ussd_string=code.ussd_string,
        tel_uri=code.tel_uri,
    )


@merchant_api_router.get("/merchants", response_model=list[MerchantResponse])
def list_merchants(container: ContainerDep) -> list[MerchantResponse]:
    return [_merchant_response(container, merchant.id) for merchant in container.merchants.all()]


@merchant_api_router.get("/merchants/{merchant_id}", response_model=MerchantResponse)
def get_merchant(merchant_id: str, container: ContainerDep) -> MerchantResponse:
    try:
        return _merchant_response(container, merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc


# ---- charges (scan-to-pay checkout) -----------------------------------------
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


def _status_of(container: Container, charge: Charge) -> str:
    tx_state = None
    if charge.transaction_id is not None:
        try:
            tx_state = container.store.get(charge.transaction_id).state
        except KeyError:
            tx_state = None
    return charge_status(charge, tx_state)


def _charge_response(container: Container, charge: Charge) -> ChargeResponse:
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


@merchant_api_router.post("/charges", response_model=ChargeResponse)
def create_charge(body: CreateChargeRequest, container: ContainerDep) -> ChargeResponse:
    """Create a charge for a posted amount. Returns the charge + the path to its QR."""
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
    return _charge_response(container, charge)


@merchant_api_router.get("/charges/{charge_id}", response_model=ChargeResponse)
def get_charge(charge_id: str, container: ContainerDep) -> ChargeResponse:
    """The charge's current state — the console polls this to watch it go Paid."""
    try:
        charge = container.charges.get(charge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    return _charge_response(container, charge)


@merchant_api_router.get("/charges/{charge_id}/qr.svg")
def charge_qr(charge_id: str, request: Request, container: ContainerDep) -> Response:
    """A scannable QR (printable SVG) encoding the customer pay page for this specific charge."""
    try:
        container.charges.get(charge_id)  # validate it exists
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    pay_url = f"{request.base_url}customer/?charge={charge_id}"
    buff = io.BytesIO()
    segno.make(pay_url, error="m").save(buff, kind="svg", scale=6, border=2)
    return Response(content=buff.getvalue(), media_type="image/svg+xml")
