"""HTTP transport for inbound provider callbacks.

Two kinds:
  - **pawaPay signed callbacks** — pawaPay POSTs the final deposit / payout / refund outcome; the
    route reads the raw body + headers and delegates to the application service. A bad signature is
    a 401, everything else returns 200 with a status.
  - **On-net operator confirmations** — for a same-network (on-net) collection, the operator
    confirms it moved the money straight to the merchant; we correlate by the persisted op-id and
    drive ``OnNetOrchestrator.on_confirm``. Sandbox/simulator only until each operator's callback
    signature is verified (see ``onnet_callback``).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..application.webhooks import process_pawapay_callback
from ..domains.transactions.on_net import OnNetOrchestrator
from ..domains.transactions.state_machine import TxState
from ..integrations.pawapay.signatures import SignatureError
from .container import ContainerDep

webhook_router = APIRouter()


@webhook_router.post("/webhooks/pawapay", response_class=Response)
async def pawapay_webhook(request: Request, container: ContainerDep) -> Response:
    raw_body = await request.body()
    try:
        status = process_pawapay_callback(
            store=container.store,
            rail=container.rail,
            ledger=container.ledger,
            public_key_pem=container.pawapay_public_key,
            method=request.method,
            path=request.url.path,
            host=request.headers.get("host", ""),
            headers=dict(request.headers),
            raw_body=raw_body,
            now=int(time.time()),
        )
    except SignatureError as exc:
        raise HTTPException(status_code=401, detail=f"invalid signature: {exc}") from exc
    return Response(content=status, media_type="text/plain")


class OperatorCallback(BaseModel):
    """An operator's on-net confirmation: the op-id we persisted when we requested the direct
    collection, plus the outcome. Real operators POST their own signed formats (M-Pesa Response URL,
    Airtel callback); this is the provider-neutral internal shape the simulator/sandbox uses until
    each operator's adapter + signature scheme are wired."""

    op_id: str
    success: bool


@webhook_router.post("/webhooks/onnet/{provider}", response_class=Response)
def onnet_callback(provider: str, body: OperatorCallback, container: ContainerDep) -> Response:
    """Resolve an on-net (same-network) collection: the operator confirms it moved the money
    straight to the merchant. We correlate by the persisted op-id and drive ``on_confirm`` — the
    on-net counterpart of the pawaPay webhook applier.

    ⚠ Sandbox/simulator only (404 in production). Unlike the pawaPay webhook (RFC-9421 signed) this
    has no authentication yet, and it can mark a payment *paid* — so it is gated off the real-money
    path until the live operator adapter and its per-operator signature verification land."""
    if not container.demo_controls_enabled:
        raise HTTPException(status_code=404, detail="on-net callback is sandbox/simulator only")
    if provider not in container.direct_rails:
        raise HTTPException(status_code=404, detail=f"no on-net rail for provider {provider}")
    transaction = container.store.find_by_op_id(body.op_id)
    if transaction is None:
        return Response(content="unmatched: no transaction for that op-id", media_type="text/plain")
    # Idempotent: only a transaction still awaiting its on-net confirmation is advanced; a replay
    # (already resolved, or never on-net) is a no-op — mirroring the state-guarded pawaPay applier.
    if transaction.state is not TxState.COLLECTION_PENDING:
        return Response(
            content=f"ignored: not awaiting confirmation (state={transaction.state.value})",
            media_type="text/plain",
        )
    OnNetOrchestrator(container.store, container.direct_rails[provider], container.ledger).on_confirm(
        transaction.id, success=body.success
    )
    return Response(content="applied", media_type="text/plain")
