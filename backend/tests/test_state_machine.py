"""Transaction state machine: legal paths, illegal transitions, terminals."""

from __future__ import annotations

import itertools

from drc_pay_api.domains.transactions.state_machine import (
    TERMINAL_STATES,
    IllegalTransition,
    TxState,
    assert_transition,
    can_transition,
    is_terminal,
)


def test_happy_path() -> None:
    path = [
        TxState.INITIATED,
        TxState.COLLECTION_PENDING,
        TxState.COLLECTION_SUCCEEDED,
        TxState.PAYOUT_PENDING,
        TxState.PAYOUT_SUCCEEDED,
    ]
    for src, dst in itertools.pairwise(path):
        assert can_transition(src, dst), f"{src} -> {dst} should be legal"
        assert_transition(src, dst)  # must not raise
    assert is_terminal(TxState.PAYOUT_SUCCEEDED)


def test_refund_path() -> None:
    path = [
        TxState.PAYOUT_PENDING,
        TxState.PAYOUT_FAILED,
        TxState.REFUND_PENDING,
        TxState.REFUNDED,
    ]
    for src, dst in itertools.pairwise(path):
        assert_transition(src, dst)
    assert is_terminal(TxState.REFUNDED)


def test_illegal_transition_raises() -> None:
    try:
        assert_transition(TxState.INITIATED, TxState.PAYOUT_SUCCEEDED)
    except IllegalTransition as exc:
        assert exc.src is TxState.INITIATED
        assert exc.dst is TxState.PAYOUT_SUCCEEDED
    else:
        raise AssertionError("expected IllegalTransition")


def test_terminal_states_have_no_exits() -> None:
    assert (
        frozenset({TxState.COLLECTION_FAILED, TxState.PAYOUT_SUCCEEDED, TxState.REFUNDED})
        == TERMINAL_STATES
    )
    for state in TERMINAL_STATES:
        assert not can_transition(state, TxState.MANUAL_REVIEW)


def test_manual_review_is_not_terminal() -> None:
    assert not is_terminal(TxState.MANUAL_REVIEW)
    assert can_transition(TxState.MANUAL_REVIEW, TxState.REFUND_PENDING)


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_state_machine: all passed")
