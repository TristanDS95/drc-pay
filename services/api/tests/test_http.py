"""HTTP API: the merchant payment flow exercised through real ASGI calls (TestClient).

Uses the seeded demo merchant ``m_alpha`` (Alpha Gas Station, settles to AIRTEL).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.http.container import Container
from drc_pay_api.main import create_app

from fakes import FakePaymentRail, FakePredictor


def _client() -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_successful_payment_settles_merchant_net_of_fee() -> None:
    client = _client()
    response = client.post(
        "/transactions",
        json={
            "customer_msisdn": "243800000001",
            "merchant_id": "m_alpha",
            "amount": "10.00",
            "currency": "USD",
            "scenario": "success",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "payout_succeeded"
    assert body["merchant_id"] == "m_alpha"
    assert body["merchant_name"] == "Alpha Gas Station"
    assert body["fee"] == "0.10"  # 1% of 10.00 (MDR)
    # The customer paid 10.00; the merchant nets 9.90; we keep 0.10.
    merchant = [line for line in body["ledger"] if line["account"] == "merchant:external"]
    revenue = [line for line in body["ledger"] if line["account"] == "revenue:fees"]
    assert merchant and merchant[0]["amount"] == "9.90"
    assert revenue and revenue[0]["amount"] == "0.10"
    assert client.get(f"/transactions/{body['id']}").json()["state"] == "payout_succeeded"


def test_settlement_failure_refunds_the_customer() -> None:
    response = _client().post(
        "/transactions",
        json={
            "customer_msisdn": "243800000001",
            "merchant_id": "m_alpha",
            "amount": "10.00",
            "scenario": "payout_fail",
        },
    )
    body = response.json()
    assert body["state"] == "refunded"
    assert "payout_failed" in body["history"]


def test_unknown_merchant_returns_404() -> None:
    response = _client().post(
        "/transactions",
        json={"customer_msisdn": "243a", "merchant_id": "does-not-exist", "amount": "10.00"},
    )
    assert response.status_code == 404


def test_unknown_transaction_returns_404() -> None:
    assert _client().get("/transactions/does-not-exist").status_code == 404


def test_idempotent_retry_returns_the_same_transaction() -> None:
    client = _client()
    payload = {"customer_msisdn": "243a", "merchant_id": "m_alpha", "amount": "10.00", "scenario": "success"}
    headers = {"Idempotency-Key": "tap-abc-123"}
    first = client.post("/transactions", json=payload, headers=headers).json()
    second = client.post("/transactions", json=payload, headers=headers).json()
    assert first["id"] == second["id"]  # same transaction, not a new one
    assert len(client.get("/transactions").json()) == 1  # only one was created


def test_different_idempotency_keys_create_different_transactions() -> None:
    client = _client()
    payload = {"customer_msisdn": "243a", "merchant_id": "m_alpha", "amount": "10.00", "scenario": "success"}
    a = client.post("/transactions", json=payload, headers={"Idempotency-Key": "k1"}).json()
    b = client.post("/transactions", json=payload, headers={"Idempotency-Key": "k2"}).json()
    assert a["id"] != b["id"]
    assert len(client.get("/transactions").json()) == 2


def test_no_idempotency_key_creates_a_new_transaction_each_time() -> None:
    client = _client()
    payload = {"customer_msisdn": "243a", "merchant_id": "m_alpha", "amount": "10.00", "scenario": "success"}
    client.post("/transactions", json=payload)
    client.post("/transactions", json=payload)
    assert len(client.get("/transactions").json()) == 2


def test_customer_provider_override_is_used() -> None:
    body = _client().post(
        "/transactions",
        json={
            "customer_msisdn": "243a",
            "merchant_id": "m_alpha",
            "amount": "10.00",
            "scenario": "success",
            "customer_provider": "ORANGE_COD",
        },
    ).json()
    assert body["customer_provider"] == "ORANGE_COD"
    # The merchant operator comes from the merchant record (Alpha settles to AIRTEL).
    assert body["merchant_provider"] == "AIRTEL_COD"


def test_live_rail_leaves_transaction_pending_and_resolves_provider() -> None:
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        predictor=FakePredictor("AIRTEL_COD"),
        simulated=False,
    )
    body = TestClient(app).post(
        "/transactions",
        json={"customer_msisdn": "243a", "merchant_id": "m_alpha", "amount": "10.00"},
    ).json()
    # No demo play-out on the live rail: it stops after the collection request, awaiting
    # the async signed callback. The customer operator was resolved via predict-provider.
    assert body["state"] == "collection_pending"
    assert body["customer_provider"] == "AIRTEL_COD"
    assert body["deposit_id"] == f"dep-{body['id']}"  # op-id persisted
    assert body["payout_id"] is None  # settlement hasn't been requested yet


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_http: all passed")
