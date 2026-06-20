"""Application service: starting a merchant payment — shared by every channel.

The HTTP API and the USSD channel are both *thin callers*: each collects (customer,
merchant, amount) in its own way — a JSON body, a USSD session — then calls
``start_merchant_payment`` here, which owns the channel-agnostic glue (resolve each
wallet's operator, drive the orchestrator, and for the demo play out a simulated
outcome). This is the "USSD is another caller into the same domain services, never a
reimplementation" rule from our standards, made concrete.

This module depends only on the domain (the ``Orchestrator``, ``Merchant``, ``Money``) —
never on any channel/transport — so it can sit under all of them.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Protocol

from ..domains.ledger.money import Money
from ..domains.merchants.models import Merchant
from ..domains.transactions.on_net import OnNetOrchestrator
from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.ports import (
    DirectCollectRail,
    LedgerPort,
    PaymentRail,
    Recorder,
    TransactionStore,
)
from ..domains.transactions.pricing import default_fee
from ..integrations.pawapay.client import ProviderPrediction
from .routing import use_on_net

# Demo fallback operator: used only when no override is given and no live predictor is
# wired (the simulator ignores the provider anyway). The live rail always resolves a real
# operator via predict-provider or an explicit override.
DEMO_PROVIDER = "VODACOM_MPESA_COD"


class Predictor(Protocol):
    """Resolves a phone number to its mobile-money operator (pawaPay predict-provider).
    Present only when a live pawaPay rail is configured."""

    def predict_provider(self, phone_number: str) -> ProviderPrediction: ...


def resolve_provider(predictor: Predictor | None, msisdn: str, override: str | None) -> str:
    """Operator for a wallet: explicit override → predict-provider (live rail) → demo."""
    if override:
        return override
    if predictor is not None:
        predicted = predictor.predict_provider(msisdn).provider
        if predicted:
            return predicted
    return DEMO_PROVIDER


def play_out(orchestrator: Orchestrator, transaction_id: str, scenario: str) -> None:
    """Drive the simulated pawaPay callbacks for a scenario — the same handlers the real
    webhooks call. Used by channels when the in-process simulator rail is active; the live
    rail's outcome arrives via the signed callback instead."""
    if scenario == "collection_fail":
        orchestrator.on_collection_result(transaction_id, success=False)
        return
    orchestrator.on_collection_result(transaction_id, success=True)
    if scenario == "success":
        orchestrator.on_payout_result(transaction_id, success=True)
        return
    orchestrator.on_payout_result(transaction_id, success=False)  # -> refund
    orchestrator.on_refund_result(transaction_id, success=scenario != "refund_fail")


def start_merchant_payment(
    *,
    store: TransactionStore,
    ledger: LedgerPort,
    rail: PaymentRail,
    direct_rails: Mapping[str, DirectCollectRail],
    on_net_providers: frozenset[str],
    predictor: Predictor | None,
    simulated: bool,
    customer_msisdn: str,
    merchant: Merchant,
    amount: Money,
    customer_provider_override: str | None = None,
    idempotency_key: str | None = None,
    scenario: str = "success",
    defer: bool = False,
    recorder: Recorder | None = None,
) -> str:
    """Resolve operators, ROUTE the payment (on-net direct vs. routed pawaPay), start it, and — on
    the simulator — play out the demo ``scenario``. Returns the new transaction id. The merchant's
    settlement target is server-derived, never client-set. This is the single dispatch point every
    channel (HTTP, USSD, charge) inherits, so the routing decision is made once, in one place.

    Routing: when the payer and merchant share an operator AND we hold an on-net rail for it, the
    operator moves the money straight to the merchant in one cheap leg (``OnNetOrchestrator``).
    Otherwise — cross-network, or an operator with no on-net rail (e.g. Orange) — it takes the
    two-leg pawaPay flow (``Orchestrator``). The provider can only be known after resolution, which
    is why the decision lives here and not inside either orchestrator.

    ``defer`` (simulator only) skips the play-out, leaving the transaction *pending* as if awaiting
    the operator's / pawaPay's callback — used to demonstrate a callback (or the reconciliation
    safety net) healing a payment whose outcome arrived later. On the live rail there is no play-out
    regardless: the real outcome always arrives asynchronously via callback."""
    customer_provider = resolve_provider(predictor, customer_msisdn, customer_provider_override)
    merchant_provider = resolve_provider(
        predictor, merchant.settlement_msisdn, merchant.settlement_provider
    )
    transaction_id = uuid.uuid4().hex

    # On-net (same-network) direct flow — one leg straight to the merchant, no fee, no pawaPay. Only
    # taken when we actually hold a rail for the shared operator; otherwise fall through to pawaPay.
    direct_rail = direct_rails.get(customer_provider)
    if direct_rail is not None and use_on_net(customer_provider, merchant_provider, on_net_providers):
        on_net = OnNetOrchestrator(store, direct_rail, ledger, recorder)
        on_net.start(
            transaction_id=transaction_id,
            payer_msisdn=customer_msisdn,
            merchant_msisdn=merchant.settlement_msisdn,
            amount=amount,
            provider=customer_provider,
            merchant_id=merchant.id,
            idempotency_key=idempotency_key,
        )
        if simulated and not defer:
            # On-net is a single leg: the only outcome that can fail is the collection itself, so a
            # post-collection scenario (payout_fail / refund_fail) simply confirms as paid.
            on_net.on_confirm(transaction_id, success=scenario != "collection_fail")
        return transaction_id

    # Routed (pawaPay) two-leg flow. Fee = the real round-trip cost for this network pair
    # (pass-through, no margin yet), derivable only once both operators are known — never the client.
    orchestrator = Orchestrator(store, rail, ledger, recorder)
    fee = default_fee(amount, customer_provider, merchant_provider)
    orchestrator.start_transaction(
        transaction_id=transaction_id,
        customer_msisdn=customer_msisdn,
        merchant_msisdn=merchant.settlement_msisdn,
        amount=amount,
        fee=fee,
        customer_provider=customer_provider,
        merchant_provider=merchant_provider,
        merchant_id=merchant.id,
        idempotency_key=idempotency_key,
    )
    if simulated and not defer:
        play_out(orchestrator, transaction_id, scenario)
    return transaction_id
