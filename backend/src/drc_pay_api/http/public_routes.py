"""Public, customer-facing endpoints — reachable WITHOUT the merchant password, so a customer
who scans a merchant's QR can pay from their own phone.

These exist for testing against the sandbox/simulator: production uses the real USSD channel, and
the payment-creating endpoint here is gated to off-the-real-money path (simulator or sandbox), 404
in production (see ``Container.demo_controls_enabled``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..adapters.memory import ListRecorder
from ..application.payments import start_merchant_payment
from ..domains.charges.models import charge_status, is_payable
from ..domains.ledger.money import Money
from ..domains.transactions.models import MERCHANT_ATTESTED
from ..integrations.pawapay.providers import PROVIDER_DISPLAY_NAMES
from .dependencies import ContainerDep

public_router = APIRouter()


@public_router.get("/public/providers")
def public_providers() -> dict[str, str]:
    """Provider code -> display name. The single source both UIs read so their labels can't drift
    (the merchant console and the customer page had kept separate, diverging maps)."""
    return PROVIDER_DISPLAY_NAMES


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
    # Either pay a specific charge (amount + merchant come from it, server-authoritative)…
    charge_id: str | None = None
    # …or pay a merchant a client-supplied amount directly (the no-charge fallback / direct API).
    merchant_id: str = ""
    amount: str = ""
    outcome: str = "success"  # success | decline | refund
    payer_network: str = "vodacom"  # vodacom | airtel | orange — the customer's operator


class PayResponse(BaseModel):
    transaction_id: str
    state: str
    amount: str
    currency: str
    fee: str  # the per-network-pair fee the merchant absorbs
    merchant_nets: str  # amount − fee, server-derived (never recomputed client-side)
    customer_provider: str | None = None  # resolved payer operator
    merchant_provider: str | None = None  # resolved merchant (payout) operator
    merchant_name: str
    trace: list[str]
    # On-net (same-network): the customer pays the merchant DIRECTLY on the operator's rail, so the
    # page shows a hand-off, not an in-app result. False/null on the routed (pawaPay) path.
    on_net: bool = False
    pay_to_till: str | None = (
        None  # the merchant's operator "buy goods" till — PREFERRED when present
    )
    pay_to_msisdn: str | None = None  # the merchant's number the customer sends to (fallback)
    pay_to_operator: str | None = None  # the shared operator (e.g. AIRTEL_COD)


class PublicTransaction(BaseModel):
    """The minimal status a payer's page needs to poll until a payment resolves — no settlement
    number, no ledger, no counterparties."""

    transaction_id: str
    state: str
    amount: str
    currency: str
    merchant_name: str | None = None
    history: list[str] = Field(
        default_factory=list
    )  # ordered states, so the page can show progress


class PublicCharge(BaseModel):
    """What the payer's page needs to pay a charge — merchant + the locked amount + live status."""

    charge_id: str
    merchant_name: str
    short_code: str
    amount: str
    currency: str
    status: str


@public_router.get("/public/merchant/{merchant_id}", response_model=PublicMerchant)
def public_merchant(merchant_id: str, container: ContainerDep) -> PublicMerchant:
    """The minimal merchant info a customer needs to pay — name + till, no settlement details."""
    try:
        merchant = container.merchants.get(merchant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="merchant not found") from exc
    return PublicMerchant(id=merchant.id, name=merchant.name, short_code=merchant.short_code)


@public_router.get("/public/transaction/{transaction_id}", response_model=PublicTransaction)
def public_transaction(transaction_id: str, container: ContainerDep) -> PublicTransaction:
    """Read-only status of a payment so the payer's page can poll until it confirms. On the live
    rail ``/pay`` returns while the deposit is still pending; the final outcome lands via pawaPay's
    callback moments later, and the page polls this to catch up. Sandbox/simulator only (like
    ``/pay``); exposes no settlement number, ledger, or counterparty details."""
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


@public_router.get("/public/charge/{charge_id}", response_model=PublicCharge)
def public_charge(charge_id: str, container: ContainerDep) -> PublicCharge:
    """Minimal, public info for paying a charge: merchant, the locked amount, and live status."""
    try:
        charge = container.charges.get(charge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="charge not found") from exc
    merchant = container.merchants.get(charge.merchant_id)
    tx_state = None
    if charge.transaction_id is not None:
        try:
            tx_state = container.store.get(charge.transaction_id).state
        except KeyError:
            tx_state = None
    return PublicCharge(
        charge_id=charge.id,
        merchant_name=merchant.name,
        short_code=merchant.short_code,
        amount=charge.amount.to_major_str(),
        currency=charge.amount.currency,
        status=charge_status(charge, tx_state),
    )


@public_router.post("/pay", response_model=PayResponse)
def pay(body: PayRequest, container: ContainerDep) -> PayResponse:
    """A customer pays a merchant (sandbox/simulator only). ``outcome`` chooses the happy path or a
    failure, so the whole merchant-side flow can be exercised end to end."""
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="customer pay is sandbox/simulator only")
    if body.outcome not in _OUTCOMES:
        raise HTTPException(status_code=422, detail=f"unknown outcome: {body.outcome}")
    if body.payer_network not in _NETWORKS:
        raise HTTPException(status_code=422, detail=f"unknown payer network: {body.payer_network}")
    # Resolve the merchant + amount: from a charge (server-authoritative) or directly.
    charge = None
    if body.charge_id:
        try:
            charge = container.charges.get(body.charge_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="charge not found") from exc
        charge_tx_state = None
        if charge.transaction_id is not None:
            try:
                charge_tx_state = container.store.get(charge.transaction_id).state
            except KeyError:
                charge_tx_state = None
        if not is_payable(charge, charge_tx_state):
            raise HTTPException(status_code=409, detail="this charge has already been paid")
        merchant = container.merchants.get(charge.merchant_id)
        amount = charge.amount
    else:
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
        f"customer scanned {merchant.name}'s QR · pays {amount.to_major_str()} USD "
        f"· network={body.payer_network} · outcome={body.outcome}"
    )
    transaction_id = start_merchant_payment(
        store=container.store,
        ledger=container.ledger,
        rail=container.rail,
        predictor=container.predictor,
        simulated=container.simulated,
        customer_msisdn=customer_msisdn,
        merchant=merchant,
        amount=amount,
        customer_provider_override=customer_provider,
        scenario=scenario,
        recorder=recorder,
    )
    if charge is not None:
        charge.transaction_id = transaction_id
        container.charges.save(charge)
    tx = container.store.get(transaction_id)
    on_net = tx.provenance == MERCHANT_ATTESTED
    return PayResponse(
        transaction_id=tx.id,
        state=tx.state.value,
        amount=tx.amount.to_major_str(),
        currency=tx.amount.currency,
        fee=tx.fee.to_major_str(),
        merchant_nets=(tx.amount - tx.fee).to_major_str(),
        customer_provider=tx.customer_provider,
        merchant_provider=tx.merchant_provider,
        merchant_name=merchant.name,
        trace=recorder.messages,
        on_net=on_net,
        pay_to_till=merchant.operator_till if on_net else None,
        pay_to_msisdn=merchant.settlement_msisdn if on_net else None,
        pay_to_operator=tx.merchant_provider if on_net else None,
    )
