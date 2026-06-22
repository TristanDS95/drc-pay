"""Parsing pawaPay callback bodies into neutral CallbackEvents (the confirmed v2 flat shape)."""
from __future__ import annotations

from drc_pay_api.integrations.pawapay.callbacks import parse_callback


def test_deposit_completed() -> None:
    ev = parse_callback({"depositId": "dep-1", "status": "COMPLETED"})
    assert ev is not None
    assert (ev.kind, ev.op_id, ev.success) == ("deposit", "dep-1", True)


def test_payout_failed() -> None:
    ev = parse_callback({"payoutId": "pay-1", "status": "FAILED"})
    assert ev is not None
    assert (ev.kind, ev.op_id, ev.success) == ("payout", "pay-1", False)


def test_refund_completed() -> None:
    ev = parse_callback({"refundId": "ref-1", "status": "COMPLETED"})
    assert ev is not None
    assert (ev.kind, ev.op_id, ev.success) == ("refund", "ref-1", True)


def test_non_terminal_status_ignored() -> None:
    assert parse_callback({"depositId": "dep-1", "status": "ACCEPTED"}) is None
    assert parse_callback({"depositId": "dep-1", "status": "SUBMITTED"}) is None


def test_unrecognised_body_ignored() -> None:
    assert parse_callback({"status": "COMPLETED"}) is None  # no op-id field
    assert parse_callback({}) is None


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_pawapay_callbacks: all passed")
