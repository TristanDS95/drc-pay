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
from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ..ussd.session import UssdHandler, UssdRequest

ussd_router = APIRouter()

# A mobile number: optional leading '+' then 6-15 ASCII digits (E.164-ish). Matched with
# ``fullmatch`` and ``[0-9]`` (not ``\d``) so a trailing newline (``$`` would allow one) or
# Unicode/fullwidth digits cannot slip through — the msisdn is stored on the transaction and
# rendered in the merchant console, so junk here is an injection vector.
_MSISDN_RE = re.compile(r"\+?[0-9]{6,15}")

# Upper bound on the accumulated-input field. A real USSD conversation is at most a few dozen
# characters (``till*amount*choice`` plus a handful of re-prompts); this just refuses a
# multi-megabyte body that would otherwise be split into a huge list — a cheap memory/CPU DoS.
_MAX_TEXT_LEN = 512

# How many admitted requests between amortized sweeps of the limiter's key map. Caps the map at
# its working set — distinct msisdns seen within a trailing window, plus up to this many keys of
# slack — instead of leaking one entry per msisdn ever seen. A unique-msisdn spray can no longer
# grow it without bound over time; it plateaus at peak-distinct-keys-per-window.
_SWEEP_EVERY = 1024


class SlidingWindowLimiter:
    """Per-key request cap over a rolling window. One instance per app (``app.state``), so
    tests get a fresh limiter per ``create_app()``."""

    # Default 15/min: comfortably above the worst-case *legal* session (dial + up to 3 tries each on
    # till, amount, and confirm ≈ 10 requests), so a fumbling but honest customer is never cut off
    # mid-payment, while a spray of hundreds/min is still braked. (Counting requests, not completed
    # sessions, is the coarse-but-simple unit; a per-session limiter would be tighter — future work.)
    def __init__(self, limit: int = 15, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._ops_since_sweep = 0

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._sweep_if_due(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _sweep_if_due(self, now: float) -> None:
        # Without this, setdefault leaks one entry per distinct key forever (a key seen once is
        # never revisited to prune its now-empty deque). Amortized O(keys) every _SWEEP_EVERY calls
        # drops every key whose most recent hit has aged out of the window.
        self._ops_since_sweep += 1
        if self._ops_since_sweep < _SWEEP_EVERY:
            return
        self._ops_since_sweep = 0
        stale = [k for k, d in self._hits.items() if not d or now - d[-1] > self._window]
        for k in stale:
            del self._hits[k]


class UssdHttpRequest(BaseModel):
    session_id: str
    msisdn: str
    text: str = Field(
        default="", max_length=_MAX_TEXT_LEN
    )  # accumulated input ("" on initial dial)

    @field_validator("msisdn")
    @classmethod
    def _valid_msisdn(cls, value: str) -> str:
        if not _MSISDN_RE.fullmatch(value):
            raise ValueError("msisdn must be 6-15 digits, optionally prefixed with '+'")
        # Canonicalize to digits-only so '+243…' and '243…' are ONE identity everywhere downstream
        # — the rate-limit bucket and the idempotency key — never two.
        return value.removeprefix("+")

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
    # Aggregator auth: enforced whenever the secret is configured. Compare on encoded bytes —
    # Starlette decodes headers as latin-1, and secrets.compare_digest raises TypeError (→ 500)
    # on a str carrying any non-ASCII char, so a crafted header could otherwise crash the endpoint
    # instead of being cleanly rejected.
    # Auth failure is an aggregator/infrastructure error, not a customer-facing one (a correctly
    # configured aggregator always sends the secret, and the console dial-simulator runs only where
    # the secret is unset), so a plain 401 is the right signal — never reached mid-session.
    if settings.ussd_shared_secret:
        supplied = request.headers.get("x-ussd-secret", "")
        if not secrets.compare_digest(
            supplied.encode("utf-8"), settings.ussd_shared_secret.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="invalid USSD shared secret")
    # Rate limit per customer number — the unit an abuser would spray prompts at. A throttled
    # customer IS in a live session, so answer with a wire-format END (200) they can actually read,
    # not a JSON 429 the aggregator would surface as a generic operator error.
    if not _limiter(request).allow(body.msisdn):
        return Response(content=_handler(request).rate_limited_wire(), media_type="text/plain")
    result = _handler(request).handle(
        UssdRequest(session_id=body.session_id, msisdn=body.msisdn, text=body.text)
    )
    return Response(content=result.to_wire(), media_type="text/plain")
