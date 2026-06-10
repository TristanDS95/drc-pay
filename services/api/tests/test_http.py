"""HTTP API: the payment flow exercised through real ASGI calls (TestClient)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_successful_transfer_books_the_fee() -> None:
    client = _client()
    response = client.post(
        "/transactions",
        json={
            "payer_msisdn": "243800000001",
            "payee_msisdn": "243810000002",
            "amount": "10.00",
            "currency": "USD",
            "scenario": "success",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "payout_succeeded"
    assert body["fee"] == "0.10"  # 1% of 10.00
    revenue = [line for line in body["ledger"] if line["account"] == "revenue:fees"]
    assert revenue and revenue[0]["amount"] == "0.10"
    # the transfer is fetchable by id
    assert client.get(f"/transactions/{body['id']}").json()["state"] == "payout_succeeded"


def test_payout_failure_refunds_the_payer() -> None:
    response = _client().post(
        "/transactions",
        json={
            "payer_msisdn": "x",
            "payee_msisdn": "y",
            "amount": "10.00",
            "scenario": "payout_fail",
        },
    )
    body = response.json()
    assert body["state"] == "refunded"
    assert "payout_failed" in body["history"]


def test_unknown_transaction_returns_404() -> None:
    assert _client().get("/transactions/does-not-exist").status_code == 404


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_http: all passed")
