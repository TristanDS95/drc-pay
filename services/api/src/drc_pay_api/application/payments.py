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
from ..domains.transactions.orchestrator import Orchestrator
from ..integrations.pawapay.client import ProviderPrediction

# Demo fallback operator: used only when no override is given and no live predictor is
# wired (the simulator ignores the provider anyway). The live rail always resolves a real
# operator via predict-provider or an explicit override.
DEMO_PROVIDER = "VODACOM_MPESA_COD"


class Predictor(Protocol):
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
    rail's outcome arrives via webhook (Phase D) instead."""
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
    orchestrator: Orchestrator,
    *,
    predictor: Predictor | None,
    simulated: bool,
    customer_msisdn: str,
    merchant: Merchant,
    amount: Money,
    fee: Money,
    customer_provider_override: str | None = None,
    idempotency_key: str | None = None,
    scenario: str = "success",
) -> str:
    """Resolve operators, start the transaction (collect from the customer, settle to the
    merchant), and — on the simulator — play out the demo ``scenario``. Returns the new
    transaction id. The merchant's settlement target is server-derived, never client-set."""
    customer_provider = resolve_provider(predictor, customer_msisdn, customer_provider_override)
    merchant_provider = resolve_provider(
        predictor, merchant.settlement_msisdn, merchant.settlement_provider
    )
    transaction_id = uuid.uuid4().hex
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
    if simulated:
        play_out(orchestrator, transaction_id, scenario)
    return transaction_id
