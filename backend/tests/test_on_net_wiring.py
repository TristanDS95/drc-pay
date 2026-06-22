"""On-net routing, wired end to end through HTTP.

A same-network payment takes the one-leg direct flow (no fee, no pawaPay), confirms as paid, and a
deferred one is resolved by the operator-confirmation callback. Contrast with test_public_routes.py
(cross-network → the routed pawaPay flow) and test_on_net.py (the OnNetOrchestrator in isolation):
here the dispatch in application.start_merchant_payment AND the /webhooks/onnet callback are
exercised together against the in-process SimulatedDirectRail.

Demo merchant operators: m_alpha → AIRTEL_COD, m_beta → ORANGE_COD, m_gamma → VODACOM_MPESA_COD.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryLedger, InMemoryTransactionStore
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.http.container import Container
from drc_pay_api.integrations.simulated_direct import SimulatedDirectRail
from drc_pay_api.main import create_app

from fakes import FakePaymentRail


def _client() -> TestClient:
    return TestClient(create_app())


# ---- the simulated direct rail ----------------------------------------------
def test_simulated_direct_rail_records_and_returns_a_correlatable_op_id() -> None:
    rail = SimulatedDirectRail()
    op_id = rail.request_direct_collection(
        transaction_id="t1", payer_msisdn="243a", merchant_msisdn="243b",
        amount=Money.from_major("3.00", "USD"), provider="AIRTEL_COD",
    )
    assert op_id == "sim-onnet-t1"  # deterministic → a later callback can correlate by op-id
    assert rail.collections == [
        ("t1", "243a", "243b", Money.from_major("3.00", "USD"), "AIRTEL_COD")
    ]


# ---- routing: same-network → on-net (one leg, no fee) -----------------------
def test_pay_same_network_takes_the_on_net_one_leg() -> None:
    # m_alpha settles to AIRTEL_COD; an Airtel payer is same-network → the direct rail, not pawaPay.
    body = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "airtel"}
    ).json()
    assert body["state"] == "payout_succeeded"  # paid — the shared terminal
    assert body["fee"] == "0.00"  # on-net: no fee leg, the merchant keeps the full amount
    assert body["customer_provider"] == body["merchant_provider"] == "AIRTEL_COD"
    assert any("on-net" in line for line in body["trace"])  # the one-leg path, not a pawaPay settle


def test_pay_same_network_vodacom_is_also_on_net() -> None:
    # m_gamma settles to VODACOM_MPESA_COD; a Vodacom payer is same-network → on-net too.
    body = _client().post(
        "/pay", json={"merchant_id": "m_gamma", "amount": "4.00", "payer_network": "vodacom"}
    ).json()
    assert body["state"] == "payout_succeeded"
    assert body["fee"] == "0.00"


def test_pay_cross_network_stays_on_the_routed_pawapay_flow() -> None:
    # Vodacom payer → Airtel merchant: different networks → the two-leg pawaPay flow, with a fee.
    body = _client().post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "vodacom"}
    ).json()
    assert body["state"] == "payout_succeeded"
    assert body["fee"] != "0.00"  # the real per-pair round-trip cost, absorbed by the merchant


def test_pay_same_network_orange_stays_routed() -> None:
    # m_beta settles to ORANGE_COD; Orange has no in-app push, so even same-network it routes through
    # pawaPay (Orange is excluded from on_net_providers).
    body = _client().post(
        "/pay", json={"merchant_id": "m_beta", "amount": "10.00", "payer_network": "orange"}
    ).json()
    assert body["state"] == "payout_succeeded"
    assert body["fee"] != "0.00"


def test_sim_toggle_runs_on_net_on_a_live_sandbox_container() -> None:
    # The demo toggle: a live (simulated=False) sandbox container wired with a SimulatedDirectRail
    # still takes the on-net path AND confirms inline — the inline confirm keys off the rail type, not
    # the pawaPay flag — so on-net is visible on the deployed sandbox without a real operator.
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        simulated=False,
        environment="sandbox",  # so the public /pay path is reachable, like the real sandbox
        direct_rails={"AIRTEL_COD": SimulatedDirectRail()},
        on_net_providers=frozenset({"AIRTEL_COD"}),
    )
    body = TestClient(app).post(
        "/pay", json={"merchant_id": "m_alpha", "amount": "10.00", "payer_network": "airtel"}
    ).json()
    assert body["state"] == "payout_succeeded"  # on-net confirmed inline despite the live pawaPay rail
    assert body["fee"] == "0.00"


def test_charge_paid_on_net_shows_paid() -> None:
    # The decision item 5: a charge paid on-net shows "paid" in the console/customer flow.
    client = _client()
    charge_id = client.post(
        "/charges", json={"merchant_id": "m_alpha", "amount": "7.50"}
    ).json()["id"]
    paid = client.post("/pay", json={"charge_id": charge_id, "payer_network": "airtel"}).json()
    assert paid["state"] == "payout_succeeded"
    assert paid["fee"] == "0.00"  # on-net
    charge = client.get(f"/public/charge/{charge_id}").json()
    assert charge["status"] == "paid"


# ---- the operator-confirmation callback (the live seam, tested offline) ------
def _start_deferred_on_net(client: TestClient) -> dict:
    """A same-network (Airtel) payment, deferred → stays collection_pending, awaiting the operator's
    confirmation callback (no inline play-out)."""
    return client.post(
        "/transactions",
        json={
            "customer_msisdn": "243aaa",
            "merchant_id": "m_alpha",
            "amount": "6.00",
            "scenario": "success",
            "customer_provider": "AIRTEL_COD",
            "defer": True,
        },
    ).json()


def test_deferred_on_net_payment_is_resolved_by_the_operator_callback() -> None:
    client = _client()
    tx = _start_deferred_on_net(client)
    assert tx["state"] == "collection_pending"  # awaiting the operator
    assert tx["fee"] == "0.00"
    assert tx["deposit_id"] == f"sim-onnet-{tx['id']}"  # op-id persisted for correlation

    resp = client.post(
        "/webhooks/onnet/AIRTEL_COD", json={"op_id": tx["deposit_id"], "success": True}
    )
    assert resp.status_code == 200 and resp.text == "applied"
    assert client.get(f"/transactions/{tx['id']}").json()["state"] == "payout_succeeded"


def test_operator_callback_is_idempotent_on_replay() -> None:
    client = _client()
    tx = _start_deferred_on_net(client)
    payload = {"op_id": tx["deposit_id"], "success": True}
    assert client.post("/webhooks/onnet/AIRTEL_COD", json=payload).text == "applied"
    # A replay after the payment already resolved is a no-op (state-guarded), not a double-apply.
    replay = client.post("/webhooks/onnet/AIRTEL_COD", json=payload)
    assert replay.status_code == 200 and replay.text.startswith("ignored")
    assert client.get(f"/transactions/{tx['id']}").json()["state"] == "payout_succeeded"


def test_operator_callback_failure_fails_the_collection() -> None:
    client = _client()
    tx = _start_deferred_on_net(client)
    resp = client.post(
        "/webhooks/onnet/AIRTEL_COD", json={"op_id": tx["deposit_id"], "success": False}
    )
    assert resp.text == "applied"
    assert client.get(f"/transactions/{tx['id']}").json()["state"] == "collection_failed"


def test_operator_callback_unmatched_op_id_is_a_noop() -> None:
    resp = _client().post(
        "/webhooks/onnet/AIRTEL_COD", json={"op_id": "sim-onnet-nope", "success": True}
    )
    assert resp.status_code == 200 and resp.text.startswith("unmatched")


def test_operator_callback_unknown_provider_is_404() -> None:
    # ORANGE_COD has no on-net rail (Orange isn't on-net), so the callback is rejected.
    resp = _client().post("/webhooks/onnet/ORANGE_COD", json={"op_id": "x", "success": True})
    assert resp.status_code == 404


def test_operator_callback_is_404_off_the_demo_path() -> None:
    # A production container (live rail) 404s the callback: it has no per-operator signature
    # verification yet, so it must not be exposed on the real-money path.
    app = create_app()
    app.state.container = Container(
        store=InMemoryTransactionStore(),
        ledger=InMemoryLedger(),
        rail=FakePaymentRail(),
        simulated=False,
        environment="production",
    )
    resp = TestClient(app).post("/webhooks/onnet/AIRTEL_COD", json={"op_id": "x", "success": True})
    assert resp.status_code == 404


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_on_net_wiring: all passed")
