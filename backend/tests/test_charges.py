"""Charges (merchant-posted checkouts): SQL store round-trip + the create → pay → paid flow.

This is the scan-to-pay-a-posted-amount path: the merchant posts an amount, the QR carries the
charge id, and the customer is charged exactly that — the amount is server-authoritative, never
taken from the client.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from drc_pay_api.adapters.sql import Base, SqlChargeStore
from drc_pay_api.domains.charges.models import Charge
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.main import create_app

from conftest import as_merchant


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _client() -> TestClient:
    # Logged in as the demo merchant "alpha" (m_alpha) — the merchant API is session-gated.
    return as_merchant(TestClient(create_app()))


def test_charge_store_roundtrip() -> None:
    store = SqlChargeStore(_factory())
    store.save(Charge(id="c1", merchant_id="m_alpha", amount=Money(1250, "USD")))
    got = store.get("c1")
    assert got.merchant_id == "m_alpha"
    assert got.amount == Money(1250, "USD")
    assert got.transaction_id is None
    got.transaction_id = "t1"  # link a payment
    store.save(got)
    assert store.get("c1").transaction_id == "t1"


def test_create_charge_and_public_view() -> None:
    client = _client()
    created = client.post("/charges", json={"merchant_id": "m_alpha", "amount": "12.50"}).json()
    assert created["status"] == "awaiting_payment"
    assert created["amount"] == "12.50"
    assert created["qr_svg_path"] == f"/charges/{created['id']}/qr.svg"
    qr = client.get(created["qr_svg_path"])
    assert qr.status_code == 200 and "image/svg" in qr.headers["content-type"]
    # the public view a customer's page fetches after scanning
    pub = client.get(f"/public/charge/{created['id']}").json()
    assert pub["merchant_name"] == "Alpha Gas Station"
    assert pub["amount"] == "12.50"
    assert pub["short_code"] == "1001"
    assert pub["status"] == "awaiting_payment"


def test_pay_a_charge_uses_its_amount_and_marks_it_paid() -> None:
    client = _client()
    charge_id = client.post(
        "/charges", json={"merchant_id": "m_alpha", "amount": "12.50"}
    ).json()["id"]
    # Server-authoritative: a client-supplied amount is ignored when charge_id is given.
    paid = client.post(
        "/pay", json={"charge_id": charge_id, "amount": "999", "payer_network": "vodacom"}
    ).json()
    assert paid["state"] == "payout_succeeded"
    assert paid["amount"] == "12.50"  # from the charge, not the client's "999"
    charge = client.get(f"/charges/{charge_id}").json()
    assert charge["status"] == "paid"
    assert charge["transaction_id"] == paid["transaction_id"]


def test_paying_a_charge_twice_is_rejected() -> None:
    client = _client()
    charge_id = client.post(
        "/charges", json={"merchant_id": "m_alpha", "amount": "5.00"}
    ).json()["id"]
    assert client.post(
        "/pay", json={"charge_id": charge_id, "payer_network": "vodacom"}
    ).status_code == 200
    second = client.post("/pay", json={"charge_id": charge_id, "payer_network": "vodacom"})
    assert second.status_code == 409  # already paid


def test_pay_unknown_charge_is_404() -> None:
    assert _client().post(
        "/pay", json={"charge_id": "nope", "payer_network": "vodacom"}
    ).status_code == 404


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_charges: all passed")
