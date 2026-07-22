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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..jobs.reconciliation.sweep import run_reconciliation
from ..seed import DEMO_LOGINS
from .dependencies import ContainerDep

demo_router = APIRouter()


class DemoLogin(BaseModel):
    username: str
    password: str
    provider: str | None = None  # settlement operator code (e.g. AIRTEL_COD); frontend names it


@demo_router.get("/demo/credentials", response_model=list[DemoLogin])
def demo_credentials(container: ContainerDep) -> list[DemoLogin]:
    """The seeded demo merchants' console logins — so demoing stays one copy-paste.

    **Passwords are returned on LOCAL only.** This endpoint is deliberately reachable without the
    shared site password (browsers don't reliably attach cached Basic credentials to ``fetch``), so
    on a deployed environment it would publish working merchant logins to anyone who asked — and
    the merchant console is now public, which would also show a real business "Demo accounts - one
    click signs you in" on the sign-in page.

    A deployed environment therefore gets an EMPTY list rather than a 404: the console uses a
    successful response as its "this is a demo environment" signal for the developer view, so
    answering 200-with-nothing keeps that working while publishing no credentials. The demo
    merchants still exist and can be signed into by anyone who knows the password.
    """
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="demo controls are disabled in production")
    if container.environment != "local":
        return []
    out: list[DemoLogin] = []
    for merchant_id, user, pw in DEMO_LOGINS:
        try:
            provider = container.merchants.get(merchant_id).settlement_provider
        except KeyError:
            provider = None
        out.append(DemoLogin(username=user, password=pw, provider=provider))
    return out


class ReconcileItem(BaseModel):
    transaction_id: str
    kind: str  # deposit | payout | refund
    disposition: str  # resolved_success | still_pending | …


class ReconcileResponse(BaseModel):
    swept: int  # pending transactions examined this sweep
    resolved: int  # how many advanced (a missed outcome applied)
    items: list[ReconcileItem]


@demo_router.post("/demo/reconcile", response_model=ReconcileResponse)
def demo_reconcile(container: ContainerDep) -> ReconcileResponse:
    """Run one reconciliation sweep against the simulator and report what it healed."""
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
