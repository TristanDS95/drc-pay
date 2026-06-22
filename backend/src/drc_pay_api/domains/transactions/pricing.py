"""Pricing — what the merchant is charged to send.

Policy (2026-06): **pass-through cost only, no margin yet.** The fee is the real pawaPay
round-trip cost for the network pair — the collection (deposit) fee on the *payer's* operator
plus the payout (disbursement) fee on the *merchant's* settlement operator. Adding a margin on
top is the open pricing decision (ADR 0005); when it's set, layer it in here.

Source: pawaPay's published DRC rates, recorded in the research repo at
``02-findings/cross-cutting/fees-and-costs.md`` (Medium-High confidence). Isolating the policy
here means the orchestrator never hard-codes a fee.
"""
from __future__ import annotations

from ..ledger.money import Money

# pawaPay published per-leg fees for DRC, in basis points (1 bp = 0.01%).
# Collection (deposit) — charged on the PAYER's operator:
_COLLECT_BPS: dict[str, int] = {
    "VODACOM_MPESA_COD": 250,  # 2.5%
    "AIRTEL_COD": 300,  # 3.0%
    "ORANGE_COD": 300,  # 3.0%
}
# Disbursement (payout) — charged on the MERCHANT's settlement operator:
_PAYOUT_BPS: dict[str, int] = {
    "VODACOM_MPESA_COD": 200,  # 2.0%
    "AIRTEL_COD": 200,  # 2.0%
    "ORANGE_COD": 100,  # 1.0%
}
# Conservative fallback for an unrecognised operator — never silently *under*charge.
_DEFAULT_COLLECT_BPS = 300
_DEFAULT_PAYOUT_BPS = 200


def collection_cost(amount: Money, payer_provider: str) -> Money:
    """pawaPay's collection (deposit) fee on the *payer's* operator — our cost for the collect
    leg, booked as an expense. Estimated from pawaPay's published per-leg rate; their callback
    doesn't return the exact figure, so reconcile against pawaPay's settlement statements."""
    bps = _COLLECT_BPS.get(payer_provider, _DEFAULT_COLLECT_BPS)
    return Money(amount.amount_minor * bps // 10_000, amount.currency)


def payout_cost(amount: Money, merchant_provider: str) -> Money:
    """pawaPay's payout (disbursement) fee on the *merchant's* operator — our cost for the
    payout leg, booked as an expense. Estimated from the published per-leg rate (see above)."""
    bps = _PAYOUT_BPS.get(merchant_provider, _DEFAULT_PAYOUT_BPS)
    return Money(amount.amount_minor * bps // 10_000, amount.currency)


def default_fee(amount: Money, payer_provider: str, merchant_provider: str) -> Money:
    """The fee the merchant absorbs (MDR). Today it is *exactly* the pawaPay round-trip cost —
    the collection fee on the payer's operator plus the payout fee on the merchant's
    (pass-through, no margin yet). Margin is the open pricing decision (ADR 0005): when set,
    add it here on top of the two leg costs, and the orchestrator books the surplus to revenue."""
    return collection_cost(amount, payer_provider) + payout_cost(amount, merchant_provider)
