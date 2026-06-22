"""HTTP transport for the USSD channel — the aggregator POSTs each step here.

The body is the provider-neutral scaffold ({session_id, msisdn, text}); adapting to a
specific USSD aggregator's wire format (form fields, the full ``*``-joined text) is a
small, flagged change confined to this boundary. The reply is the conventional CON/END
string. The handler shares the app's container, so a USSD payment is visible through the
same /transactions API and dashboard.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..ussd.session import UssdHandler, UssdRequest

ussd_router = APIRouter()


class UssdHttpRequest(BaseModel):
    session_id: str
    msisdn: str
    text: str = ""  # the user's latest input ("" on the initial dial)


def _handler(request: Request) -> UssdHandler:
    handler: UssdHandler = request.app.state.ussd_handler
    return handler


@ussd_router.post("/ussd", response_class=Response)
def ussd(body: UssdHttpRequest, request: Request) -> Response:
    result = _handler(request).handle(
        UssdRequest(session_id=body.session_id, msisdn=body.msisdn, text=body.text)
    )
    return Response(content=result.to_wire(), media_type="text/plain")
