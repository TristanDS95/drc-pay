"""Routing — decide whether a payment is on-net (same-network) or routed via pawaPay.

Same-network payments settle merchant-direct on the operator's own rail and are recorded/confirmed by
us (``on_net.py``) — see ADR 0009. Cross-network payments take the routed pawaPay two-leg flow
(``orchestrator.py``). This is the single place that decision lives. ``on_net_providers`` is the set of
operators we facilitate on-net for.
"""
from __future__ import annotations


def use_on_net(payer_provider: str, merchant_provider: str, on_net_providers: frozenset[str]) -> bool:
    """True iff this is an on-net (same-network) payment we facilitate: the payer and merchant share an
    operator that is in ``on_net_providers``. Otherwise it routes through pawaPay."""
    return payer_provider == merchant_provider and payer_provider in on_net_providers
