"""Public, customer-facing endpoints — reachable WITHOUT the merchant password, so a customer
who scans a merchant's QR can pay from their own phone.

These exist for testing against the sandbox/simulator: production uses the real USSD channel, and
the payment-creating endpoint here is gated to off-the-real-money path (simulator or sandbox), 404
in production (see ``Container.demo_controls_enabled``).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..adapters.memory import ListRecorder
from ..application.payments import start_merchant_payment
from ..domains.ledger.money import Money
from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.pricing import default_fee
from .container import Container

public_router = APIRouter()

# Outcome → (customer test MSISDN for the live sandbox, scenario for the simulator). On the
# simulator the scenario drives the result; on the live sandbox rail the test number does (…789
# succeeds, …049 = insufficient balance). "refund" (collect succeeds, settle fails) plays out
# fully on the simulator.
_OUTCOMES: dict[str, tuple[str, str]] = {
    "success": ("243813456789", "success"),
    "decline": ("243813456049", "collection_fail"),
    "refund": ("243813456789", "payout_fail"),
}


class PublicMerchant(BaseModel):
    id: str
    name: str
    short_code: str


class PayRequest(BaseModel):
    merchant_id: str
    amount: str
    outcome: str = "success"  # success | decline | refund


class PayResponse(BaseModel):
    transaction_id: str
    state: str
    amount: str
    currency: str
    merchant_name: str
    trace: list[str]


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


@public_router.get("/public/merchant/{merchant_id}", response_model=PublicMerchant)
def public_merchant(merchant_id: str, request: Request) -> PublicMerchant:
    """The minimal merchant info a customer needs to pay — name + till, no settlement details."""
    try:
        merchant = _container(request).merchants.get(merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    return PublicMerchant(id=merchant.id, name=merchant.name, short_code=merchant.short_code)


@public_router.post("/pay", response_model=PayResponse)
def pay(body: PayRequest, request: Request) -> PayResponse:
    """A customer pays a merchant (sandbox/simulator only). ``outcome`` chooses the happy path or a
    failure, so the whole merchant-side flow can be exercised end to end."""
    container = _container(request)
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="customer pay is sandbox/simulator only")
    if body.outcome not in _OUTCOMES:
        raise HTTPException(status_code=422, detail=f"unknown outcome: {body.outcome}")
    try:
        amount = Money.from_major(body.amount, "USD")
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid amount: {exc}") from exc
    if not amount.is_positive:
        raise HTTPException(status_code=422, detail="amount must be positive")
    try:
        merchant = container.merchants.get(body.merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc

    customer_msisdn, scenario = _OUTCOMES[body.outcome]
    recorder = ListRecorder()
    recorder.record(
        f"customer scanned {merchant.name}'s QR · pays {body.amount} USD · outcome={body.outcome}"
    )
    orchestrator = Orchestrator(container.store, container.rail, container.ledger, recorder)
    transaction_id = start_merchant_payment(
        orchestrator,
        predictor=container.predictor,
        simulated=container.simulated,
        customer_msisdn=customer_msisdn,
        merchant=merchant,
        amount=amount,
        fee=default_fee(amount),
        scenario=scenario,
    )
    tx = container.store.get(transaction_id)
    return PayResponse(
        transaction_id=tx.id,
        state=tx.state.value,
        amount=tx.amount.to_major_str(),
        currency=tx.amount.currency,
        merchant_name=merchant.name,
        trace=recorder.messages,
    )
