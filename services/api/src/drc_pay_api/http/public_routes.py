"""Public, customer-facing endpoints — reachable WITHOUT the merchant password, so a customer
who scans a merchant's QR can pay from their own phone.

These exist for testing against the sandbox/simulator: production uses the real USSD channel, and
the payment-creating endpoint here is gated to off-the-real-money path (simulator or sandbox), 404
in production (see ``Container.demo_controls_enabled``).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..adapters.memory import ListRecorder
from ..application.payments import start_merchant_payment
from ..domains.ledger.money import Money
from ..domains.transactions.orchestrator import Orchestrator
from .container import Container

public_router = APIRouter()

# pawaPay DRC sandbox test numbers: the operator prefix picks the PAYER's network, and the last
# three digits pick the OUTCOME (789 = success, 049 = insufficient funds). On the simulator the
# scenario string drives the result instead. Source: docs.pawapay.io/v2/docs/test_numbers.
_NETWORKS: dict[str, str] = {  # UI value → pawaPay provider code
    "vodacom": "VODACOM_MPESA_COD",
    "airtel": "AIRTEL_COD",
    "orange": "ORANGE_COD",
}
_NETWORK_BASE: dict[str, str] = {  # everything but the final 3-digit outcome suffix
    "vodacom": "243813456",
    "airtel": "243973456",
    "orange": "243893456",
}
# Outcome → (deposit suffix, simulator scenario). "refund" (collect ok, settle fails) only plays
# out on the simulator — a live refund needs a payout-failing merchant, not a payer number.
_OUTCOMES: dict[str, tuple[str, str]] = {
    "success": ("789", "success"),
    "decline": ("049", "collection_fail"),
    "refund": ("789", "payout_fail"),
}


class PublicMerchant(BaseModel):
    id: str
    name: str
    short_code: str


class PayRequest(BaseModel):
    merchant_id: str
    amount: str
    outcome: str = "success"  # success | decline | refund
    payer_network: str = "vodacom"  # vodacom | airtel | orange — the customer's operator


class PayResponse(BaseModel):
    transaction_id: str
    state: str
    amount: str
    currency: str
    fee: str  # the per-network-pair fee the merchant absorbs
    customer_provider: str | None = None  # resolved payer operator
    merchant_provider: str | None = None  # resolved merchant (payout) operator
    merchant_name: str
    trace: list[str]


class PublicTransaction(BaseModel):
    """The minimal status a payer's page needs to poll until a payment resolves — no settlement
    number, no ledger, no counterparties."""

    transaction_id: str
    state: str
    amount: str
    currency: str
    merchant_name: str | None = None
    history: list[str] = Field(default_factory=list)  # ordered states, so the page can show progress


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


@public_router.get("/public/transaction/{transaction_id}", response_model=PublicTransaction)
def public_transaction(transaction_id: str, request: Request) -> PublicTransaction:
    """Read-only status of a payment so the payer's page can poll until it confirms. On the live
    rail ``/pay`` returns while the deposit is still pending; the final outcome lands via pawaPay's
    callback moments later, and the page polls this to catch up. Sandbox/simulator only (like
    ``/pay``); exposes no settlement number, ledger, or counterparty details."""
    container = _container(request)
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="not found")
    try:
        tx = container.store.get(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    merchant_name: str | None = None
    if tx.merchant_id:
        try:
            merchant_name = container.merchants.get(tx.merchant_id).name
        except KeyError:
            merchant_name = None
    return PublicTransaction(
        transaction_id=tx.id,
        state=tx.state.value,
        amount=tx.amount.to_major_str(),
        currency=tx.amount.currency,
        merchant_name=merchant_name,
        history=[s.value for s in tx.history],
    )


@public_router.post("/pay", response_model=PayResponse)
def pay(body: PayRequest, request: Request) -> PayResponse:
    """A customer pays a merchant (sandbox/simulator only). ``outcome`` chooses the happy path or a
    failure, so the whole merchant-side flow can be exercised end to end."""
    container = _container(request)
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="customer pay is sandbox/simulator only")
    if body.outcome not in _OUTCOMES:
        raise HTTPException(status_code=422, detail=f"unknown outcome: {body.outcome}")
    if body.payer_network not in _NETWORKS:
        raise HTTPException(status_code=422, detail=f"unknown payer network: {body.payer_network}")
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

    suffix, scenario = _OUTCOMES[body.outcome]
    customer_msisdn = _NETWORK_BASE[body.payer_network] + suffix
    customer_provider = _NETWORKS[body.payer_network]
    recorder = ListRecorder()
    recorder.record(
        f"customer scanned {merchant.name}'s QR · pays {body.amount} USD "
        f"· network={body.payer_network} · outcome={body.outcome}"
    )
    orchestrator = Orchestrator(container.store, container.rail, container.ledger, recorder)
    transaction_id = start_merchant_payment(
        orchestrator,
        predictor=container.predictor,
        simulated=container.simulated,
        customer_msisdn=customer_msisdn,
        merchant=merchant,
        amount=amount,
        customer_provider_override=customer_provider,
        scenario=scenario,
    )
    tx = container.store.get(transaction_id)
    return PayResponse(
        transaction_id=tx.id,
        state=tx.state.value,
        amount=tx.amount.to_major_str(),
        currency=tx.amount.currency,
        fee=tx.fee.to_major_str(),
        customer_provider=tx.customer_provider,
        merchant_provider=tx.merchant_provider,
        merchant_name=merchant.name,
        trace=recorder.messages,
    )
