"""build_container selects the rail from config: the live pawaPay rail when both
credentials are present, otherwise the in-process simulator.
"""
from __future__ import annotations

import httpx

from drc_pay_api.http.container import build_container
from drc_pay_api.integrations.pawapay.client import PawaPayClient
from drc_pay_api.integrations.pawapay.rail import PawaPayRail
from drc_pay_api.integrations.pawapay.simulator import SimulatedPaymentRail
from drc_pay_api.integrations.simulated_direct import SimulatedDirectRail


def test_defaults_to_the_simulator() -> None:
    container = build_container()
    assert isinstance(container.rail, SimulatedPaymentRail)
    assert container.simulated is True
    assert container.predictor is None
    assert container.poller is container.rail  # the simulator doubles as the status poller


def test_selects_pawapay_when_credentials_are_set() -> None:
    container = build_container(
        pawapay_base_url="https://api.sandbox.pawapay.io", pawapay_api_token="tkn"
    )
    assert isinstance(container.rail, PawaPayRail)
    assert container.simulated is False
    assert container.predictor is not None  # the client doubles as the provider predictor
    assert container.poller is container.predictor  # …and as the status poller


def test_partial_pawapay_credentials_fall_back_to_the_simulator() -> None:
    # Only a base URL, no token: not enough to go live — stay on the simulator.
    container = build_container(pawapay_base_url="https://api.sandbox.pawapay.io")
    assert isinstance(container.rail, SimulatedPaymentRail)
    assert container.simulated is True


def test_simulator_wires_on_net_rails_for_airtel_and_vodacom() -> None:
    # Off the live rail, the on-net-capable operators (Airtel, Vodacom — not Orange) get a simulated
    # direct rail, so a same-network payment exercises the one-leg flow offline.
    container = build_container()
    assert container.on_net_providers == frozenset({"AIRTEL_COD", "VODACOM_MPESA_COD"})
    assert set(container.direct_rails) == {"AIRTEL_COD", "VODACOM_MPESA_COD"}
    assert all(isinstance(rail, SimulatedDirectRail) for rail in container.direct_rails.values())


def test_live_rail_has_no_on_net_rails_yet() -> None:
    # The M-Pesa/Airtel adapters aren't implemented, so a live rail holds no on-net rails and routes
    # every payment through pawaPay (graceful per-operator fallback) until an adapter lands.
    container = build_container(
        pawapay_base_url="https://api.sandbox.pawapay.io", pawapay_api_token="tkn"
    )
    assert container.direct_rails == {}
    assert container.on_net_providers == frozenset()


def test_onnet_simulate_toggle_wires_sim_on_net_on_a_live_rail() -> None:
    # The demo toggle wires the in-process SimulatedDirectRail even on a live pawaPay rail, so on-net
    # routing is *visible* on the sandbox (simulated — fakes the confirmation, moves no real money).
    container = build_container(
        pawapay_base_url="https://api.sandbox.pawapay.io",
        pawapay_api_token="tkn",
        onnet_simulate=True,
    )
    assert container.simulated is False  # the pawaPay rail is still live
    assert container.on_net_providers == frozenset({"AIRTEL_COD", "VODACOM_MPESA_COD"})
    assert all(isinstance(rail, SimulatedDirectRail) for rail in container.direct_rails.values())


def test_seeds_demo_merchants() -> None:
    container = build_container()
    assert container.merchants.get_by_short_code("1001") is not None
    assert {m.id for m in container.merchants.all()} == {"m_alpha", "m_beta", "m_gamma"}


def test_ensure_callback_public_key_fetches_when_live_and_unset() -> None:
    pem = "-----BEGIN PUBLIC KEY-----\nMFkwEC...\n-----END PUBLIC KEY-----\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "HTTP_EC_P256_KEY:1", "key": pem}])

    client = PawaPayClient(
        base_url="https://x", api_token="t",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    container = build_container()  # simulated, no key
    container.pawapay_client = client
    container.pawapay_public_key = ""
    container.ensure_callback_public_key()
    assert container.pawapay_public_key == pem


def test_ensure_callback_public_key_is_noop_when_already_set() -> None:
    # A statically-supplied key wins; no client call, no overwrite, no crash.
    container = build_container()
    container.pawapay_public_key = "EXISTING-PEM"
    container.ensure_callback_public_key()
    assert container.pawapay_public_key == "EXISTING-PEM"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_container: all passed")
