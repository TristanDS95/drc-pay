"""HTTP endpoints — a thin layer over the orchestrator.

POST /transactions starts a transfer and (for the demo) plays out a simulated pawaPay
outcome chosen by ``scenario``, so one call runs the whole flow with no external
services. Try it from the auto-generated interactive docs at /docs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from ..domains.ledger.money import Money
from ..domains.transactions.models import Transaction
from ..domains.transactions.pricing import default_fee
from .container import Container
from .schemas import CreateTransferRequest, LedgerLine, TransferResponse

router = APIRouter()

_SCENARIOS = {"success", "payout_fail", "collection_fail", "refund_fail"}


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _play_out(container: Container, transfer_id: str, scenario: str) -> None:
    """Drive the simulated pawaPay callbacks for the chosen scenario — the same
    handlers pawaPay's real webhooks will call in production."""
    orchestrator = container.orchestrator
    if scenario == "collection_fail":
        orchestrator.on_collection_result(transfer_id, success=False)
        return
    orchestrator.on_collection_result(transfer_id, success=True)
    if scenario == "success":
        orchestrator.on_payout_result(transfer_id, success=True)
        return
    orchestrator.on_payout_result(transfer_id, success=False)  # -> refund
    orchestrator.on_refund_result(transfer_id, success=scenario != "refund_fail")


def _to_response(container: Container, transaction: Transaction) -> TransferResponse:
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
    return TransferResponse(
        id=transaction.id,
        payer_msisdn=transaction.payer_msisdn,
        payee_msisdn=transaction.payee_msisdn,
        amount=transaction.amount.to_major_str(),
        fee=transaction.fee.to_major_str(),
        currency=transaction.amount.currency,
        state=transaction.state.value,
        history=[s.value for s in transaction.history],
        ledger=lines,
    )


@router.post("/transactions", response_model=TransferResponse)
def create_transfer(body: CreateTransferRequest, request: Request) -> TransferResponse:
    if body.scenario not in _SCENARIOS:
        raise HTTPException(status_code=422, detail=f"unknown scenario: {body.scenario}")
    try:
        amount = Money.from_major(body.amount, body.currency)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid amount/currency: {exc}") from exc
    if not amount.is_positive:
        raise HTTPException(status_code=422, detail="amount must be positive")

    container = _container(request)
    transfer_id = uuid.uuid4().hex
    container.orchestrator.start_transfer(
        transfer_id=transfer_id,
        payer_msisdn=body.payer_msisdn,
        payee_msisdn=body.payee_msisdn,
        amount=amount,
        fee=default_fee(amount),
    )
    _play_out(container, transfer_id, body.scenario)
    return _to_response(container, container.store.get(transfer_id))


@router.get("/transactions/{transfer_id}", response_model=TransferResponse)
def get_transfer(transfer_id: str, request: Request) -> TransferResponse:
    container = _container(request)
    try:
        transaction = container.store.get(transfer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return _to_response(container, transaction)


@router.get("/transactions", response_model=list[TransferResponse])
def list_transfers(request: Request) -> list[TransferResponse]:
    container = _container(request)
    return [_to_response(container, tx) for tx in container.store.all()]
