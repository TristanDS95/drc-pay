"""The USSD channel: a customer pays a merchant, driving the *same* orchestrator as the
HTTP API. Fully offline. Aggregators send the full accumulated input each step
(`text = "1001*10*1"`), so a scanned/dialed QR (`*123*1001*10#`) is just a session that
starts pre-filled — the dial-through fast-path.

Uses the seeded demo merchant ``m_alpha`` (till 1001, Alpha Gas Station).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.http.container import build_container
from drc_pay_api.main import create_app
from drc_pay_api.ussd.session import UssdHandler, UssdRequest, run_session


def test_ussd_happy_path_creates_and_settles_a_payment() -> None:
    container = build_container()
    handler = UssdHandler(container)
    sid, msisdn = "sess-1", "243800000009"

    r0 = handler.handle(UssdRequest(sid, msisdn, ""))
    assert r0.continue_session and "till" in r0.message.lower()

    r1 = handler.handle(UssdRequest(sid, msisdn, "1001"))  # Alpha Gas Station
    assert r1.continue_session and "Alpha Gas Station" in r1.message

    r2 = handler.handle(UssdRequest(sid, msisdn, "1001*10"))  # accumulated text
    assert r2.continue_session and "Confirm" in r2.message

    r3 = handler.handle(UssdRequest(sid, msisdn, "1001*10*1"))  # confirm
    assert not r3.continue_session
    assert "initiated" in r3.message.lower()

    txs = container.store.all()
    assert len(txs) == 1
    tx = txs[0]
    assert tx.customer_msisdn == msisdn
    assert tx.merchant_id == "m_alpha"
    assert tx.amount == Money.from_major("10.00", "USD")
    assert tx.state.value == "payout_succeeded"  # the simulator played out success


def test_ussd_qr_dial_through_jumps_to_confirm() -> None:
    # A scanned/dialed *123*1001*10# arrives as one request with the text pre-filled.
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("q1", "243a", "1001*10"))
    assert r.continue_session
    assert "Confirm" in r.message and "Alpha Gas Station" in r.message
    r2 = handler.handle(UssdRequest("q1", "243a", "1001*10*1"))
    assert not r2.continue_session
    assert len(container.store.all()) == 1


def test_ussd_qr_dial_through_till_only_asks_amount() -> None:
    # *123*1001# pre-fills just the till → straight to the amount prompt.
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("q2", "243a", "1001"))
    assert r.continue_session and "amount" in r.message.lower()


def test_ussd_unknown_till_ends_session() -> None:
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("s2", "243a", "9999"))
    assert not r.continue_session
    assert "not found" in r.message.lower()


def test_ussd_cancel_creates_no_payment() -> None:
    container = build_container()
    handler = UssdHandler(container)
    run_session(handler, "s3", "243a", ["1001", "10", "2"])  # 2 = cancel
    assert container.store.all() == []


def test_ussd_invalid_amount_ends() -> None:
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("s4", "243a", "1001*not-a-number"))
    assert not r.continue_session
    assert "invalid" in r.message.lower()


def test_ussd_run_session_helper_completes() -> None:
    container = build_container()
    handler = UssdHandler(container)
    responses = run_session(handler, "s5", "243a", ["1001", "5.00", "1"])
    assert responses[-1].continue_session is False
    assert len(container.store.all()) == 1


def test_ussd_endpoint_shares_the_transaction_store() -> None:
    client = TestClient(create_app())
    sid, msisdn = "http-1", "243800000009"
    last = None
    for text in ["", "1001", "1001*10", "1001*10*1"]:  # accumulated, as an aggregator sends
        last = client.post("/ussd", json={"session_id": sid, "msisdn": msisdn, "text": text})
        assert last.status_code == 200
    assert last is not None and last.text.startswith("END")
    # The USSD payment is visible through the same HTTP API (shared container).
    listed = client.get("/transactions").json()
    assert len(listed) == 1
    assert listed[0]["merchant_id"] == "m_alpha"
    assert listed[0]["customer_msisdn"] == msisdn


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_ussd: all passed")
