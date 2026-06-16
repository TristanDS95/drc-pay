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


def fee_basis_points(payer_provider: str, merchant_provider: str) -> int:
    """Round-trip cost in basis points: collect on the payer's operator + pay out on the
    merchant's operator (e.g. VODACOM→ORANGE = 250 + 100 = 350 bps = 3.5%)."""
    return _COLLECT_BPS.get(payer_provider, _DEFAULT_COLLECT_BPS) + _PAYOUT_BPS.get(
        merchant_provider, _DEFAULT_PAYOUT_BPS
    )


def default_fee(amount: Money, payer_provider: str, merchant_provider: str) -> Money:
    """The fee the merchant absorbs: the real pawaPay round-trip cost for this network pair
    (pass-through, no margin yet), floored to the minor unit."""
    bps = fee_basis_points(payer_provider, merchant_provider)
    return Money(amount.amount_minor * bps // 10_000, amount.currency)
