"""Composition root — wires the orchestrator to concrete adapters.

For local dev and tests this uses the in-memory store/ledger and the built-in pawaPay
simulator. Swapping in Postgres + the real pawaPay client happens here, nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..adapters.memory import InMemoryLedger, InMemoryTransactionStore
from ..domains.transactions.orchestrator import Orchestrator
from ..integrations.pawapay.simulator import SimulatedPaymentRail


@dataclass
class Container:
    store: InMemoryTransactionStore
    ledger: InMemoryLedger
    rail: SimulatedPaymentRail
    orchestrator: Orchestrator


def build_container() -> Container:
    store = InMemoryTransactionStore()
    ledger = InMemoryLedger()
    rail = SimulatedPaymentRail()
    orchestrator = Orchestrator(store, rail, ledger)
    return Container(store=store, ledger=ledger, rail=rail, orchestrator=orchestrator)
