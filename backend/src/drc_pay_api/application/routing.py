"""Rail routing — pick the on-net (direct) path or the routed (pawaPay) path for a payment.

Same-network payments can move in one cheap leg via the operator's own rail (``on_net.py`` +
``integrations.mpesa`` / ``integrations.airtel``). Cross-network — or any operator we don't yet have
an on-net rail for (e.g. Orange, whose flow is a web redirect, not an in-app push) — falls back to
the routed pawaPay two-leg flow (``orchestrator.py``). This is the single place that decision lives,
so enabling/disabling an operator's on-net rail is a one-line config change (the ``on_net_providers``
set, wired in the composition root).
"""
from __future__ import annotations


def use_on_net(payer_provider: str, merchant_provider: str, on_net_providers: frozenset[str]) -> bool:
    """True iff this payment should take the on-net direct rail: the payer and merchant share an
    operator AND we have an on-net rail for it. Otherwise it routes through pawaPay (the fallback)."""
    return payer_provider == merchant_provider and payer_provider in on_net_providers
