"""HTTP transport for the USSD channel — the aggregator POSTs each step here.

The body is the provider-neutral scaffold ({session_id, msisdn, text}); adapting to a
specific USSD aggregator's wire format (form fields, the full ``*``-joined text) is a
small, flagged change confined to this boundary. The reply is the conventional CON/END
string. The handler shares the app's container, so a USSD payment is visible through the
same /transactions API and dashboard.

This boundary also owns the channel's hardening (security roadmap, Gate A):

- **Aggregator authentication**: when ``DRCPAY_USSD_SHARED_SECRET`` is set, every request
  must carry it in ``X-USSD-Secret`` (constant-time compared) — only the contracted
  aggregator can drive the channel. Unset in local/sandbox so the console's dial
  simulator keeps working; **production refuses to boot without it** (see ``main.py``).
- **Rate limiting**: an in-process sliding window per msisdn. Without it, anyone could
  spam payment prompts to arbitrary DRC numbers (a harassment / social-engineering
  vector, even though no money moves without the payer's operator PIN). In-process is
  honest for today's single-container deploys; the shared-state limiter is a separate
  roadmap item.
"""
from __future__ import annotations

import re
import secrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from ..config import settings
from ..ussd.session import UssdHandler, UssdRequest

ussd_router = APIRouter()

# A mobile number: optional leading '+' then 6-15 digits (E.164-ish). Validating here keeps
# non-numeric junk out of the phone field — it's stored on the transaction and later rendered
# in the merchant console, so an unvalidated free-text msisdn would be an injection vector.
_MSISDN_RE = re.compile(r"^\+?\d{6,15}$")


class SlidingWindowLimiter:
    """Per-key request cap over a rolling window. One instance per app (``app.state``), so
    tests get a fresh limiter per ``create_app()``."""

    def __init__(self, limit: int = 8, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


class UssdHttpRequest(BaseModel):
    session_id: str
    msisdn: str
    text: str = ""  # the user's latest input ("" on the initial dial)

    @field_validator("msisdn")
    @classmethod
    def _valid_msisdn(cls, value: str) -> str:
        if not _MSISDN_RE.match(value):
            raise ValueError("msisdn must be 6-15 digits, optionally prefixed with '+'")
        return value

    @field_validator("session_id")
    @classmethod
    def _valid_session_id(cls, value: str) -> str:
        # The session id keys payment idempotency — an absurdly long or empty one is junk.
        if not value or len(value) > 128:
            raise ValueError("session_id must be 1-128 characters")
        return value


def _handler(request: Request) -> UssdHandler:
    handler: UssdHandler = request.app.state.ussd_handler
    return handler


def _limiter(request: Request) -> SlidingWindowLimiter:
    limiter: SlidingWindowLimiter = request.app.state.ussd_limiter
    return limiter


@ussd_router.post("/ussd", response_class=Response)
def ussd(body: UssdHttpRequest, request: Request) -> Response:
    # Aggregator auth: enforced whenever the secret is configured.
    if settings.ussd_shared_secret:
        supplied = request.headers.get("x-ussd-secret", "")
        if not secrets.compare_digest(supplied, settings.ussd_shared_secret):
            raise HTTPException(status_code=401, detail="invalid USSD shared secret")
    # Rate limit per customer number — the unit an abuser would spray prompts at.
    if not _limiter(request).allow(body.msisdn):
        raise HTTPException(status_code=429, detail="too many USSD requests for this number")
    result = _handler(request).handle(
        UssdRequest(session_id=body.session_id, msisdn=body.msisdn, text=body.text)
    )
    return Response(content=result.to_wire(), media_type="text/plain")
