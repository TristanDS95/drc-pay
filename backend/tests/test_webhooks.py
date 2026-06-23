"""The pawaPay webhook receiver, end to end: a signed deposit-completed callback advances
the transaction; bad signatures are rejected; replays and unmatched op-ids are no-ops.
"""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.application.payments import start_merchant_payment
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.http.container import Container
from drc_pay_api.main import create_app

from fakes import FakePaymentRail, pawapay_keypair, sign_pawapay_callback


def _pending_app():
    """An app whose container holds one transaction left in collection_pending (a deposit
    issued on a fake rail, awaiting pawaPay's callback), plus the matching signing key."""
    sk, pem = pawapay_keypair()
    store = InMemoryTransactionStore()
    ledger = InMemoryLedger()
    rail = FakePaymentRail()
    container = Container(
        store=store, ledger=ledger, rail=rail, simulated=False, pawapay_public_key=pem
    )
    merchant = container.merchants.get("m_alpha")
    # The customer resolves cross-network (Vodacom → Airtel) — a routed pawaPay flow, which is the
    # path this webhook test exercises.
    tx_id = start_merchant_payment(
        store=store,
        ledger=ledger,
        rail=rail,
        predictor=None,
        simulated=False,
        customer_msisdn="243800000001",
        merchant=merchant,
        amount=Money.from_major("10.00", "USD"),
    )
    app = create_app()
    app.state.container = container
    return app, sk, tx_id, store


def _callback(sk, deposit_id):
    body = json.dumps({"depositId": deposit_id, "status": "COMPLETED"}).encode()
    headers = sign_pawapay_callback(
        sk, host="testserver", path="/webhooks/pawapay", body=body, created=int(time.time())
    )
    return body, headers


def test_signed_deposit_callback_advances_transaction() -> None:
    app, sk, tx_id, store = _pending_app()
    body, headers = _callback(sk, store.get(tx_id).deposit_id)
    resp = TestClient(app).post("/webhooks/pawapay", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.text == "applied"
    # collection succeeded → settlement requested → awaiting the payout callback
    assert store.get(tx_id).state.value == "payout_pending"


def test_bad_signature_rejected_and_no_state_change() -> None:
    app, sk, tx_id, store = _pending_app()
    body, headers = _callback(sk, store.get(tx_id).deposit_id)
    headers["Signature"] = "sig1=:AAAAAAAA:"  # corrupt the signature
    resp = TestClient(app).post("/webhooks/pawapay", content=body, headers=headers)
    assert resp.status_code == 401
    assert store.get(tx_id).state.value == "collection_pending"  # untouched


def test_duplicate_callback_is_idempotent() -> None:
    app, sk, tx_id, store = _pending_app()
    deposit_id = store.get(tx_id).deposit_id
    client = TestClient(app)
    body, headers = _callback(sk, deposit_id)
    assert client.post("/webhooks/pawapay", content=body, headers=headers).status_code == 200
    after_first = store.get(tx_id).state.value  # payout_pending

    body2, headers2 = _callback(sk, deposit_id)
    replay = client.post("/webhooks/pawapay", content=body2, headers=headers2)
    assert replay.status_code == 200 and "ignored" in replay.text
    assert store.get(tx_id).state.value == after_first  # no further change


def test_unmatched_op_id_is_a_noop() -> None:
    app, sk, _, _ = _pending_app()
    body, headers = _callback(sk, "no-such-deposit-id")
    resp = TestClient(app).post("/webhooks/pawapay", content=body, headers=headers)
    assert resp.status_code == 200 and "unmatched" in resp.text


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_webhooks: all passed")
