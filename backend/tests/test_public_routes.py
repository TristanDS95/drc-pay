"""The public, no-password customer endpoints — a customer who scans a merchant's QR can read the
merchant's name and pay, choosing the outcome to exercise each merchant-side flow.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.container import Container
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


def test_public_transaction_returns_minimal_status() -> None:
    client = _client()
    paid = client.post("/pay", json={"merchant_id": "m_alpha", "amount": "10.00"}).json()
    status = client.get(f"/public/transaction/{paid['transaction_id']}").json()
    assert status["transaction_id"] == paid["transaction_id"]
    assert status["state"] == "payout_succeeded"
    assert status["amount"] == "10.00"
    assert status["merchant_name"] == "Alpha Gas Station"
    # The history drives the customer page's live "what happened" log.
    assert status["history"][-1] == "payout_succeeded"
    assert "collection_succeeded" in status["history"]
    # The payer's status view must never leak settlement details or the ledger.
    assert "settlement_msisdn" not in status
    assert "ledger" not in status


def test_public_transaction_404_for_missing() -> None:
    assert _client().get("/public/transaction/does-not-exist").status_code == 404


def test_public_transaction_blocked_in_production() -> None:
    # Like /pay, the public status view is sandbox/simulator only — a production container 404s it.
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        simulated=False,
        environment="production",
    )
    assert TestClient(app).get("/public/transaction/anything").status_code == 404


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


def test_pay_payer_network_drives_the_per_pair_fee() -> None:
    # Vodacom payer → Orange merchant (m_beta): collect 2.5% + payout 1.0% = 3.5% of 10.00.
    body = _client().post(
        "/pay", json={"merchant_id": "m_beta", "amount": "10.00", "payer_network": "vodacom"}
    ).json()
    assert body["customer_provider"] == "VODACOM_MPESA_COD"
    assert body["merchant_provider"] == "ORANGE_COD"
    assert body["fee"] == "0.35"


def test_pay_rejects_unknown_payer_network() -> None:
    resp = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10", "payer_network": "mtn"}
    )
    assert resp.status_code == 422


def _run_all() -> None:
    skip = {test_public_endpoints_bypass_the_password}
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and fn not in skip:
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_public_routes: all passed (run via pytest for the monkeypatch test)")
