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

from .status import Outcome, classify

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
            outcome = classify(str(body.get("status", "")))
            if outcome is Outcome.PENDING:
                return None  # non-terminal status → ignore
            return CallbackEvent(kind=kind, op_id=op_id, success=outcome is Outcome.SUCCESS)
    return None  # no recognised op-id field
