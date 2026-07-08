"""pawaPay async-status vocabulary — the one place that knows what a pawaPay operation
status *means*, shared by the callback receiver (a *pushed* outcome) and the reconciliation
sweep (a *polled* outcome) so the two can never drift on which statuses are terminal.

Confirmed against pawaPay's v2 docs (2026-06): terminal statuses are ``COMPLETED`` (success) and
``FAILED`` (failure); ``ACCEPTED`` / ``ENQUEUED`` / ``PROCESSING`` / ``IN_RECONCILIATION`` are
non-terminal → ``PENDING`` (fail-safe). The status endpoint wraps the operation under ``data``
(``client._status``); the callback body is flat (``callbacks.parse_callback``).
Source: https://docs.pawapay.io/v2/docs/deposits
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Outcome(str, Enum):
    """A pawaPay operation's resolved disposition, from our point of view."""

    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"  # not terminal yet — wait for a later callback / the next sweep


# Terminal pawaPay statuses. Anything else (ACCEPTED, SUBMITTED, PENDING, …) is non-terminal.
# This is the single source of truth for "done?", shared by the callback parser and the sweep.
_SUCCESS = {"COMPLETED"}
_FAILURE = {"FAILED", "REJECTED"}


def classify(raw_status: str | None) -> Outcome:
    """Map a raw pawaPay status string to an ``Outcome``. Unknown / absent / non-terminal
    statuses classify as ``PENDING`` — the fail-safe default, so we never resolve money on a
    status we don't positively recognise as terminal."""
    status = (raw_status or "").upper()
    if status in _SUCCESS:
        return Outcome.SUCCESS
    if status in _FAILURE:
        return Outcome.FAILURE
    return Outcome.PENDING


@dataclass(frozen=True)
class PawaPayStatus:
    """The result of polling a deposit / payout / refund status endpoint: the operation's
    raw status string, or ``None`` when it couldn't be read (non-2xx, unexpected shape) —
    which the caller treats as still-pending (fail-safe, leave the transaction untouched)."""

    status: str | None


class StatusPoller(Protocol):
    """The pawaPay status-polling surface the reconciliation sweep depends on. The live
    ``PawaPayClient`` implements it; tests supply a mock. Each call returns the current
    status of one operation, looked up by the pawaPay op-id we persisted for it."""

    def get_deposit_status(self, deposit_id: str) -> PawaPayStatus: ...

    def get_payout_status(self, payout_id: str) -> PawaPayStatus: ...

    def get_refund_status(self, refund_id: str) -> PawaPayStatus: ...
