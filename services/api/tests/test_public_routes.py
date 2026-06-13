"""The public, no-password customer endpoints — a customer who scans a merchant's QR can read the
merchant's name and pay, choosing the outcome to exercise each merchant-side flow.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.http.container import Container
from drc_pay_api.main import create_app

from fakes import FakePaymentRail


def _client() -> TestClient:
    return TestClient(create_app())


def test_public_merchant_info_has_no_settlement_details() -> None:
    body = _client().get("/public/merchant/m_alpha").json()
    assert body["name"] == "Alpha Gas Station"
    assert body["short_code"] == "1001"
    assert "settlement_msisdn" not in body  # the customer never sees where money settles


def test_pay_success_settles_the_merchant() -> None:
    body = _client().post("/pay", json={"merchant_id": "m_alpha", "amount": "10.00"}).json()
    assert body["state"] == "payout_succeeded"
    assert body["merchant_name"] == "Alpha Gas Station"
    assert body["trace"]  # the operations trace comes back for stakeholder testing


def test_pay_decline_moves_no_money() -> None:
    body = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "outcome": "decline"}
    ).json()
    assert body["state"] == "collection_failed"


def test_pay_refund_makes_the_customer_whole() -> None:
    body = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "outcome": "refund"}
    ).json()
    assert body["state"] == "refunded"


def test_pay_rejects_bad_outcome_and_merchant() -> None:
    client = _client()
    bad_outcome = client.post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10", "outcome": "nope"}
    )
    assert bad_outcome.status_code == 422
    assert client.post("/pay", json={"merchant_id": "ghost", "amount": "10"}).status_code == 404


def test_public_endpoints_bypass_the_password(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "basic_auth_password", "sesame")
    client = _client()
    assert client.get("/transactions").status_code == 401  # the admin API stays gated
    assert client.get("/public/merchant/m_alpha").status_code == 200  # but the customer paths are open
    paid = client.post("/pay", json={"merchant_id": "m_alpha", "amount": "5"})
    assert paid.status_code == 200


def test_pay_blocked_in_production() -> None:
    # Customer pay is sandbox/simulator only — a live production container 404s it.
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        simulated=False,
        environment="production",
    )
    resp = TestClient(app).post("/pay", json={"merchant_id": "m_alpha", "amount": "5"})
    assert resp.status_code == 404


def _run_all() -> None:
    skip = {test_public_endpoints_bypass_the_password}
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and fn not in skip:
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_public_routes: all passed (run via pytest for the monkeypatch test)")
