"""Composition root — holds the shared, persistent adapters.

For local dev and tests this is the in-memory store/ledger and the built-in pawaPay
simulator. Swapping in Postgres + the real pawaPay client happens here, nowhere else.
The orchestrator itself is built per-request (in ``routes``) with a fresh trace
recorder, so each call can return its own operations log.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..adapters.memory import InMemoryLedger, InMemoryTransactionStore
from ..integrations.pawapay.simulator import SimulatedPaymentRail


@dataclass
class Container:
    store: InMemoryTransactionStore
    ledger: InMemoryLedger
    rail: SimulatedPaymentRail


def build_container() -> Container:
    return Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=SimulatedPaymentRail(),
    )
