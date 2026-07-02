"""The demo affordances that back the web Merchant Console: a ``defer``-ed payment stays
pending (a stand-in for a missed callback), and the simulator-only ``POST /demo/reconcile``
heals it leg by leg — the same reconciliation sweep, exercised through real ASGI calls.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.container import Container
from drc_pay_api.main import create_app

from fakes import FakePaymentRail


def _client() -> TestClient:
    return TestClient(create_app())


def _pay(client: TestClient, *, defer: bool) -> dict:
    return client.post(
        "/transactions",
        json={"customer_msisdn": "243800000001", "merchant_id": "m_alpha", "amount": "10.00",
              "defer": defer},
    ).json()


def test_deferred_payment_stays_pending_with_a_sim_op_id() -> None:
    body = _pay(_client(), defer=True)
    assert body["state"] == "collection_pending"  # not played out — awaiting confirmation
    assert body["deposit_id"] == f"sim-dep-{body['id']}"  # simulator issued a pollable op-id
    assert body["payout_id"] is None  # settlement not requested yet


def test_reconciliation_heals_a_stuck_payment_leg_by_leg() -> None:
    client = _client()
    tx = _pay(client, defer=True)
    tid = tx["id"]

    # First sweep: the collection's missed outcome is found COMPLETED → settlement begins.
    first = client.post("/demo/reconcile").json()
    assert first["resolved"] == 1
    assert client.get(f"/transactions/{tid}").json()["state"] == "payout_pending"

    # Second sweep: the settlement's outcome is found COMPLETED → the merchant is paid.
    second = client.post("/demo/reconcile").json()
    assert second["resolved"] == 1
    paid = client.get(f"/transactions/{tid}").json()
    assert paid["state"] == "payout_succeeded"
    merchant = [line for line in paid["ledger"] if line["account"] == "merchant:external"]
    assert merchant and merchant[0]["amount"] == "9.55"  # net of the 4.5% cost (Vodacom→Airtel)


def test_reconcile_is_a_noop_when_nothing_is_pending() -> None:
    client = _client()
    _pay(client, defer=False)  # instant success → terminal, nothing left to heal
    result = client.post("/demo/reconcile").json()
    assert result["swept"] == 0
    assert result["resolved"] == 0


def _live_app(environment: str):
    """An app whose container is a live (non-simulated) rail in the given environment."""
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        simulated=False,
        environment=environment,
    )
    return app


def test_demo_controls_refused_in_production() -> None:
    # Off the real-money path only: a live PRODUCTION container must 404, so a production
    # deployment can never trigger reconciliation over an unauthenticated endpoint.
    assert TestClient(_live_app("production")).post("/demo/reconcile").status_code == 404


def test_demo_controls_allowed_in_sandbox() -> None:
    # Sandbox moves no real money, so the control is allowed there (your point) — it runs and
    # returns a normal (empty) summary even though this fake container has no poller wired.
    resp = TestClient(_live_app("sandbox")).post("/demo/reconcile")
    assert resp.status_code == 200
    assert resp.json()["swept"] == 0


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_demo_console: all passed")
