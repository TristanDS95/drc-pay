"""On-net (same-network) facilitate & record, through HTTP — ADR 0009.

A same-network payment is recorded as *awaiting confirmation* (we move no money); the customer is
handed off to pay the merchant directly on the operator, and a merchant "Confirm received" marks it
paid (merchant-attested). Cross-network keeps the rail-verified pawaPay flow.

Demo merchant operators: m_alpha → AIRTEL_COD, m_beta → ORANGE_COD, m_gamma → VODACOM_MPESA_COD.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_same_network_pay_is_awaiting_confirmation_not_routed() -> None:
    # m_alpha settles to AIRTEL_COD; an Airtel payer is same-network → on-net facilitate.
    body = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "airtel"}
    ).json()
    assert body["on_net"] is True
    assert body["state"] == "collection_pending"  # awaiting the merchant's confirmation, not "paid"
    assert body["fee"] == "0.00"  # we move no money and take no cut
    assert body["customer_provider"] == body["merchant_provider"] == "AIRTEL_COD"
    # The customer is told to pay the merchant directly on their operator.
    assert body["pay_to_msisdn"]  # the merchant's number
    assert body["pay_to_operator"] == "AIRTEL_COD"


def test_merchant_confirm_marks_a_charge_paid_merchant_attested() -> None:
    client = _client()
    charge_id = client.post("/charges", json={"merchant_id": "m_alpha", "amount": "7.50"}).json()["id"]
    paid = client.post("/pay", json={"charge_id": charge_id, "payer_network": "airtel"}).json()
    tx_id = paid["transaction_id"]
    assert paid["on_net"] is True and paid["state"] == "collection_pending"
    assert client.get(f"/charges/{charge_id}").json()["status"] == "processing"  # not paid yet

    # Merchant taps "Confirm received".
    confirmed = client.post(f"/transactions/{tx_id}/confirm").json()
    assert confirmed["state"] == "payout_succeeded"
    assert confirmed["provenance"] == "merchant_attested"  # honest: not rail-verified
    assert client.get(f"/charges/{charge_id}").json()["status"] == "paid"


def test_merchant_can_report_not_received() -> None:
    client = _client()
    tx_id = client.post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "5.00", "payer_network": "airtel"}
    ).json()["transaction_id"]
    body = client.post(f"/transactions/{tx_id}/confirm?received=false").json()
    assert body["state"] == "collection_failed"  # no money moved


def test_confirm_is_idempotent() -> None:
    client = _client()
    tx_id = client.post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "5.00", "payer_network": "airtel"}
    ).json()["transaction_id"]
    assert client.post(f"/transactions/{tx_id}/confirm").json()["state"] == "payout_succeeded"
    # Re-confirming a resolved payment is a no-op, not an error or a double-post.
    again = client.post(f"/transactions/{tx_id}/confirm")
    assert again.status_code == 200 and again.json()["state"] == "payout_succeeded"


def test_confirm_rejects_a_routed_payment() -> None:
    # Cross-network (Vodacom payer → Airtel merchant) → routed pawaPay, not on-net → can't be confirmed.
    client = _client()
    paid = client.post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "vodacom"}
    ).json()
    assert paid["on_net"] is False
    resp = client.post(f"/transactions/{paid['transaction_id']}/confirm")
    assert resp.status_code == 422


def test_routed_payment_is_tagged_rail_verified() -> None:
    client = _client()
    paid = client.post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "vodacom"}
    ).json()
    tx = client.get(f"/transactions/{paid['transaction_id']}").json()
    assert tx["provenance"] == "rail_verified"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_on_net_facilitate: all passed")
