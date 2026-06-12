"""HTTP endpoints — a thin layer over the orchestrator.

POST /transactions records a customer paying a registered merchant and (for the demo)
plays out a simulated pawaPay outcome chosen by ``scenario``, so one call runs the whole
flow with no external services. The response includes a human-readable ``trace`` of every
operation. Try it from the auto-generated interactive docs at /docs.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..adapters.memory import ListRecorder
from ..application.payments import start_merchant_payment
from ..domains.ledger.money import Money
from ..domains.transactions.models import Transaction
from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.pricing import default_fee
from .container import Container
from .schemas import CreateTransactionRequest, LedgerLine, TransactionResponse

router = APIRouter()

_SCENARIOS = {"success", "payout_fail", "collection_fail", "refund_fail"}


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


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


@router.post("/transactions", response_model=TransactionResponse)
def create_transaction(
    body: CreateTransactionRequest,
    request: Request,
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

    container = _container(request)

    # Resolve the merchant being paid (server-derived settlement — never trust the client).
    try:
        merchant = container.merchants.get(body.merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    if not merchant.is_active:
        raise HTTPException(status_code=422, detail="merchant is not active")

    # Idempotency: if this key was already processed, return the ORIGINAL result rather
    # than creating a second transaction — so a retry or double-tap never double-charges.
    if idempotency_key is not None:
        existing = container.store.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _to_response(
                container, existing, ["idempotent replay · key already processed; original returned"]
            )

    fee = default_fee(amount)
    recorder = ListRecorder()
    recorder.record(f"POST /transactions · {body.amount} {body.currency} · scenario={body.scenario}")
    recorder.record(f"merchant · {merchant.name} ({merchant.id}) · settle → {merchant.settlement_msisdn}")
    recorder.record(
        f"pricing · fee (MDR) = 1% of {body.amount} = {fee.to_major_str()} {body.currency} "
        f"· merchant nets {(amount - fee).to_major_str()} {body.currency}"
    )

    # The HTTP API is a thin caller: build the orchestrator, delegate to the shared
    # application service (resolve operators, start the legs, play out on the simulator).
    orchestrator = Orchestrator(container.store, container.rail, container.ledger, recorder)
    transaction_id = start_merchant_payment(
        orchestrator,
        predictor=container.predictor,
        simulated=container.simulated,
        customer_msisdn=body.customer_msisdn,
        merchant=merchant,
        amount=amount,
        fee=fee,
        customer_provider_override=body.customer_provider,
        idempotency_key=idempotency_key,
        scenario=body.scenario,
    )
    return _to_response(container, container.store.get(transaction_id), recorder.messages)


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: str, request: Request) -> TransactionResponse:
    container = _container(request)
    try:
        transaction = container.store.get(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return _to_response(container, transaction, [])


@router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(request: Request) -> list[TransactionResponse]:
    container = _container(request)
    return [_to_response(container, tx, []) for tx in container.store.all()]
