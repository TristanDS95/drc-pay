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
from typing import Protocol

from ..domains.ledger.money import Money
from ..domains.merchants.models import Merchant
from ..domains.transactions.on_net import OnNetOrchestrator
from ..domains.transactions.orchestrator import Orchestrator
from ..domains.transactions.ports import (
    DuplicateIdempotencyKey,
    IdempotentTransactionStore,
    LedgerPort,
    PaymentRail,
    Recorder,
)
from ..domains.transactions.pricing import default_fee
from ..integrations.pawapay.client import ProviderPrediction
from .routing import ON_NET_PROVIDERS, use_on_net

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
    store: IdempotentTransactionStore,
    ledger: LedgerPort,
    rail: PaymentRail,
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
    """Resolve operators, start the transaction (collect from the customer, settle to the merchant via
    pawaPay), and — on the simulator — play out the demo ``scenario``. Returns the new transaction id.
    The merchant's settlement target is server-derived, never client-set. The shared entry every channel
    (HTTP, USSD, charge) calls.

    ``defer`` (simulator only) skips the play-out, leaving the transaction *pending* as if awaiting
    pawaPay's callback — used to demonstrate the reconciliation safety net healing a payment whose
    callback never arrived. On the live rail there is no play-out: the real outcome always arrives
    asynchronously via the signed callback."""
    customer_provider = resolve_provider(predictor, customer_msisdn, customer_provider_override)
    merchant_provider = resolve_provider(
        predictor, merchant.settlement_msisdn, merchant.settlement_provider
    )

    # Idempotency (CLAUDE.md: no money-moving request may double-charge on a retry). Owned HERE so
    # every channel — HTTP, USSD, charges — inherits it without re-implementing the check. A retry
    # of an already-completed request short-circuits on this pre-check; a *concurrent* retry that
    # races past it is caught below by the store's unique-key guard. Either way, one transaction.
    if idempotency_key is not None:
        existing = store.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing.id

    transaction_id = uuid.uuid4().hex
    try:
        # On-net (same-network): the customer pays the merchant directly on the operator's own rail.
        # We record the payment as awaiting confirmation (initiate nothing, hold nothing, take no
        # fee); a merchant "Confirm received" resolves it via OnNetOrchestrator.on_confirm. ADR 0009.
        if use_on_net(customer_provider, merchant_provider, ON_NET_PROVIDERS):
            OnNetOrchestrator(store, ledger, recorder).start(
                transaction_id=transaction_id,
                payer_msisdn=customer_msisdn,
                merchant_msisdn=merchant.settlement_msisdn,
                amount=amount,
                provider=customer_provider,
                merchant_id=merchant.id,
                idempotency_key=idempotency_key,
            )
            return transaction_id

        # Routed (pawaPay) two-leg flow. Fee = the real round-trip cost for this network pair
        # (pass-through, no margin yet), derivable only once both operators are known — never the
        # client.
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
    except DuplicateIdempotencyKey:
        # Lost a concurrent race: the winner created this payment first (its first save committed
        # before ours, before either touched the rail). Return the original — never a second charge.
        if idempotency_key is not None:
            racer = store.find_by_idempotency_key(idempotency_key)
            if racer is not None:
                return racer.id
        raise
