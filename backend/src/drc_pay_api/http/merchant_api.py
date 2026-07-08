"""The merchant-facing HTTP API — every endpoint is authenticated as a specific merchant
(``CurrentMerchant``) and **scoped to that merchant's own data**: you list your payments,
confirm your receipts, charge for your shop — never anyone else's. Cross-merchant reads
return 404 (not 403), so responses don't confirm that another merchant's ids exist.

Consolidates what were three modules (transactions, merchants, charges): they share an audience
(the authenticated merchant console) and a change cadence, so they belong together. Each handler
is a thin caller — it takes the shared ``Container`` via ``ContainerDep``, validates input,
delegates to an ``application/`` service, and serializes the result. No money logic lives here.

The two ``qr.svg`` endpoints are the deliberate exception to session auth: they're loaded by
``<img>`` tags (which cannot send an Authorization header) and their content is public by
design — a QR exists to be scanned by a customer.

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
from ..container import Container
from ..domains.charges.models import Charge, charge_status
from ..domains.ledger.money import Money
from ..domains.transactions.models import MERCHANT_ATTESTED, Transaction
from ..domains.transactions.on_net import OnNetOrchestrator
from ..domains.transactions.state_machine import TxState
from .dependencies import ContainerDep, CurrentMerchant
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
        merchant_nets=(transaction.amount - transaction.fee).to_major_str(),
        currency=transaction.amount.currency,
        state=transaction.state.value,
        history=[s.value for s in transaction.history],
        ledger=lines,
        customer_provider=transaction.customer_provider,
        merchant_provider=transaction.merchant_provider,
        deposit_id=transaction.deposit_id,
        payout_id=transaction.payout_id,
        refund_id=transaction.refund_id,
        provenance=transaction.provenance,
        trace=trace,
    )


@merchant_api_router.post("/transactions", response_model=TransactionResponse)
def create_transaction(
    body: CreateTransactionRequest,
    merchant: CurrentMerchant,
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

    # The merchant being paid IS the logged-in merchant — the session, not the body, decides
    # where money settles. A mismatching body merchant_id is rejected, never honored.
    if body.merchant_id is not None and body.merchant_id != merchant.id:
        raise HTTPException(status_code=403, detail="cannot take payments for another merchant")
    if not merchant.is_active:
        raise HTTPException(status_code=422, detail="merchant is not active")

    # Idempotency: a repeated key returns the ORIGINAL result, never a second charge.
    if idempotency_key is not None:
        existing = container.store.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _to_response(
                container,
                existing,
                ["idempotent replay · key already processed; original returned"],
            )

    recorder = ListRecorder()
    recorder.record(
        f"POST /transactions · {body.amount} {body.currency} · scenario={body.scenario}"
    )
    recorder.record(
        f"merchant · {merchant.name} ({merchant.id}) · settle → {merchant.settlement_msisdn}"
    )
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


@merchant_api_router.post(
    "/transactions/{transaction_id}/confirm", response_model=TransactionResponse
)
def confirm_on_net_payment(
    transaction_id: str, merchant: CurrentMerchant, container: ContainerDep, received: bool = True
) -> TransactionResponse:
    """The merchant confirms (``received`` True, the default) or denies (``received=false``) they got an
    on-net payment directly on their operator. Marks it paid (merchant-attested) or failed. On-net only;
    idempotent — re-confirming an already-resolved payment is a no-op. Only the OWNING merchant can
    attest — this is the endpoint whose word marks money received (ADR 0009)."""
    try:
        tx = container.store.get(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    if tx.merchant_id != merchant.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    if tx.provenance != MERCHANT_ATTESTED:
        raise HTTPException(status_code=422, detail="not an on-net payment — nothing to confirm")
    if tx.state is not TxState.COLLECTION_PENDING:
        return _to_response(container, tx, [f"already resolved · state={tx.state.value}"])
    OnNetOrchestrator(container.store, container.ledger).on_confirm(
        transaction_id, success=received
    )
    verb = "received → paid" if received else "not received"
    return _to_response(
        container, container.store.get(transaction_id), [f"merchant confirmation: {verb}"]
    )


@merchant_api_router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: str, merchant: CurrentMerchant, container: ContainerDep
) -> TransactionResponse:
    try:
        transaction = container.store.get(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    if transaction.merchant_id != merchant.id:  # 404, not 403 — don't confirm the id exists
        raise HTTPException(status_code=404, detail="transaction not found")
    return _to_response(container, transaction, [])


@merchant_api_router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    merchant: CurrentMerchant, container: ContainerDep
) -> list[TransactionResponse]:
    return [
        _to_response(container, tx, [])
        for tx in container.store.all()
        if tx.merchant_id == merchant.id
    ]


# ---- merchants --------------------------------------------------------------
def merchant_profile(container: Container, merchant_id: str) -> MerchantResponse:
    """The merchant's own profile (also served as ``GET /auth/me``)."""
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
        operator_till=merchant.operator_till,
    )


@merchant_api_router.get("/merchants", response_model=list[MerchantResponse])
def list_merchants(merchant: CurrentMerchant, container: ContainerDep) -> list[MerchantResponse]:
    """One trust tier, one merchant: the list is always exactly the caller. (Kept for
    API-shape compatibility; the console boots from ``/auth/me``.)"""
    return [merchant_profile(container, merchant.id)]


@merchant_api_router.get("/merchants/{merchant_id}", response_model=MerchantResponse)
def get_merchant(
    merchant_id: str, merchant: CurrentMerchant, container: ContainerDep
) -> MerchantResponse:
    if merchant_id != merchant.id:  # 404, not 403 — don't confirm other merchants' ids
        raise HTTPException(status_code=404, detail="merchant not found")
    return merchant_profile(container, merchant.id)


# ---- charges (scan-to-pay checkout) -----------------------------------------
class CreateChargeRequest(BaseModel):
    # The charged merchant is the logged-in merchant; optional and validated when sent.
    merchant_id: str | None = None
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
def create_charge(
    body: CreateChargeRequest, merchant: CurrentMerchant, container: ContainerDep
) -> ChargeResponse:
    """Create a charge for a posted amount — for the logged-in merchant, always. Returns the
    charge + the path to its QR."""
    if body.merchant_id is not None and body.merchant_id != merchant.id:
        raise HTTPException(status_code=403, detail="cannot create charges for another merchant")
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
def get_charge(
    charge_id: str, merchant: CurrentMerchant, container: ContainerDep
) -> ChargeResponse:
    """The charge's current state — the console polls this to watch it go Paid."""
    try:
        charge = container.charges.get(charge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    if charge.merchant_id != merchant.id:  # 404, not 403 — don't confirm the id exists
        raise HTTPException(status_code=404, detail="charge not found")
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


@merchant_api_router.get("/merchants/{merchant_id}/qr.svg")
def merchant_qr(merchant_id: str, container: ContainerDep) -> Response:
    """A printable QR for the merchant's **static USSD till** — the *customer-initiated USSD*
    pathway (ADR 0006), distinct from the amount-specific charge QR above. It encodes the
    ``tel:`` dial-through (``tel:*123*1001%23``) so a scanning phone offers to dial the USSD
    code; feature phones can't scan, so the printed sticker also shows the dialable
    ``ussd_string`` for manual entry. No amount is baked in — the customer types it on the phone."""
    try:
        merchant = container.merchants.get(merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    code = merchant_payment_code(container.ussd_shortcode, merchant.short_code)
    buff = io.BytesIO()
    segno.make(code.tel_uri, error="m").save(buff, kind="svg", scale=6, border=2)
    return Response(content=buff.getvalue(), media_type="image/svg+xml")
