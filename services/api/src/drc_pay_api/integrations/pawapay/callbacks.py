"""Parse a pawaPay callback body into a neutral ``CallbackEvent`` the webhook handler can
act on. pawaPay delivers the *final* outcome of a deposit/payout/refund here.

⚠️ Provisional: the exact callback JSON is an open item until sandbox access (Phase E).
This maps the documented shape — an object carrying the op-id (``depositId`` /
``payoutId`` / ``refundId``) and a terminal status — and is structured so the field
mapping is easy to adjust once confirmed. Source: https://docs.pawapay.io/using_the_api
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Terminal statuses → did the operation succeed? Anything else (ACCEPTED, SUBMITTED,
# PENDING, …) is non-terminal and ignored (we wait for a later callback).
_SUCCESS = {"COMPLETED"}
_FAILURE = {"FAILED", "REJECTED"}

# Which op-id field identifies each leg.
_OP_FIELDS = (("deposit", "depositId"), ("payout", "payoutId"), ("refund", "refundId"))


@dataclass(frozen=True)
class CallbackEvent:
    kind: str  # "deposit" | "payout" | "refund"
    op_id: str  # the pawaPay operation id we persisted
    success: bool  # terminal outcome


def parse_callback(body: dict[str, Any]) -> CallbackEvent | None:
    """Return a terminal ``CallbackEvent``, or ``None`` if the body is unrecognised or not
    yet terminal (so the caller ignores it without error)."""
    for kind, field in _OP_FIELDS:
        op_id = body.get(field)
        if isinstance(op_id, str) and op_id:
            status = str(body.get("status", "")).upper()
            if status in _SUCCESS:
                return CallbackEvent(kind=kind, op_id=op_id, success=True)
            if status in _FAILURE:
                return CallbackEvent(kind=kind, op_id=op_id, success=False)
            return None  # non-terminal status → ignore
    return None  # no recognised op-id field
