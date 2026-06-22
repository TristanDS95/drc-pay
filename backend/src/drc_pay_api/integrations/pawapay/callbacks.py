"""Parse a pawaPay callback body into a neutral ``CallbackEvent`` the webhook handler can
act on. pawaPay delivers the *final* outcome of a deposit/payout/refund here.

Confirmed against pawaPay's v2 docs (2026-06): a callback body is **flat** — the operation
object at the top level, carrying the op-id (``depositId`` / ``payoutId`` / ``refundId``) and a
top-level ``status``. (The GET status endpoints differ: they wrap the object under ``data`` —
see ``client._status``; don't confuse the two.) Terminal statuses are classified by
``status.classify`` and confirmed against real sandbox callbacks.
Source: https://docs.pawapay.io/v2/docs/deposits
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
