"""Demo/ops HTTP controls — available **off the real-money path only** (the in-process
simulator, or the sandbox), never in production. The handler 404s and the router is not even
mounted when ``Container.demo_controls_enabled`` is False, so a live production deployment
never exposes them.

Today that means one control: trigger a reconciliation sweep, so a *pending* payment — a
``defer``-ed simulator charge, or a real sandbox payment still awaiting its callback — can be
visibly healed by polling status. The real production trigger (an authenticated admin action
or a scheduled worker) is a separate, flagged ops task.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..jobs.reconciliation.sweep import run_reconciliation
from .container import Container

demo_router = APIRouter()


class ReconcileItem(BaseModel):
    transaction_id: str
    kind: str  # deposit | payout | refund
    disposition: str  # resolved_success | still_pending | …


class ReconcileResponse(BaseModel):
    swept: int  # pending transactions examined this sweep
    resolved: int  # how many advanced (a missed outcome applied)
    items: list[ReconcileItem]


@demo_router.post("/demo/reconcile", response_model=ReconcileResponse)
def demo_reconcile(request: Request) -> ReconcileResponse:
    """Run one reconciliation sweep against the simulator and report what it healed."""
    container: Container = request.app.state.container
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="demo controls are disabled in production")
    summary = run_reconciliation(
        store=container.store, rail=container.rail, ledger=container.ledger, poller=container.poller
    )
    return ReconcileResponse(
        swept=summary.total,
        resolved=summary.resolved,
        items=[
            ReconcileItem(transaction_id=i.transaction_id, kind=i.kind, disposition=i.disposition)
            for i in summary.items
        ],
    )
