"""build_container selects the rail from config: the live pawaPay rail when both
credentials are present, otherwise the in-process simulator.
"""
from __future__ import annotations

import httpx
import pytest

from drc_pay_api.container import build_container
from drc_pay_api.integrations.pawapay.client import PawaPayClient
from drc_pay_api.integrations.pawapay.rail import PawaPayRail
from drc_pay_api.integrations.pawapay.simulator import SimulatedPaymentRail


def test_defaults_to_the_simulator() -> None:
    container = build_container()
    assert isinstance(container.rail, SimulatedPaymentRail)
    assert container.simulated is True
    assert container.predictor is None


def test_deployed_environment_refuses_to_start_without_a_database() -> None:
    # A deployed env must never silently use the ephemeral in-memory store (data loss on restart).
    with pytest.raises(RuntimeError, match="DRCPAY_DATABASE_URL"):
        build_container(environment="sandbox")


def test_local_environment_allows_in_memory() -> None:
    # Local dev/tests may run without a database.
    container = build_container(environment="local")
    assert container.simulated is True
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
