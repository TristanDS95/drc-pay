"""HTTP transport for pawaPay's signed callbacks — pawaPay POSTs the final deposit / payout / refund
outcome here. The route reads the raw body + headers and delegates to the application service; a bad
signature is a 401, everything else returns 200 with a status.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from ..application.webhooks import process_pawapay_callback
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
