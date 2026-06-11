"""HTTP endpoints — a thin layer over the orchestrator.

POST /transactions starts a transaction and (for the demo) plays out a simulated
pawaPay outcome chosen by ``scenario``, so one call runs the whole flow with no
external services. The response includes a human-readable ``trace`` of every operation.
Try it from the auto-generated interactive docs at /docs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from ..adapters.memory import ListRecorder
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


def _play_out(orchestrator: Orchestrator, transaction_id: str, scenario: str) -> None:
    """Drive the simulated pawaPay callbacks for the chosen scenario — the same
    handlers pawaPay's real webhooks will call in production."""
    if scenario == "collection_fail":
        orchestrator.on_collection_result(transaction_id, success=False)
        return
    orchestrator.on_collection_result(transaction_id, success=True)
    if scenario == "success":
        orchestrator.on_payout_result(transaction_id, success=True)
        return
    orchestrator.on_payout_result(transaction_id, success=False)  # -> refund
    orchestrator.on_refund_result(transaction_id, success=scenario != "refund_fail")


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
        payer_msisdn=transaction.payer_msisdn,
        payee_msisdn=transaction.payee_msisdn,
        amount=transaction.amount.to_major_str(),
        fee=transaction.fee.to_major_str(),
        currency=transaction.amount.currency,
        state=transaction.state.value,
        history=[s.value for s in transaction.history],
        ledger=lines,
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
    recorder.record(f"pricing · fee = 1% of {body.amount} = {fee.to_major_str()} {body.currency}")

    orchestrator = Orchestrator(container.store, container.rail, container.ledger, recorder)
    transaction_id = uuid.uuid4().hex
    orchestrator.start_transaction(
        transaction_id=transaction_id,
        payer_msisdn=body.payer_msisdn,
        payee_msisdn=body.payee_msisdn,
        amount=amount,
        fee=fee,
        idempotency_key=idempotency_key,
    )
    _play_out(orchestrator, transaction_id, body.scenario)
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
