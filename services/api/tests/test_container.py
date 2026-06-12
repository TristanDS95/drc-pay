"""build_container selects the rail from config: the live pawaPay rail when both
credentials are present, otherwise the in-process simulator.
"""
from __future__ import annotations

from drc_pay_api.http.container import build_container
from drc_pay_api.integrations.pawapay.rail import PawaPayRail
from drc_pay_api.integrations.pawapay.simulator import SimulatedPaymentRail


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


def test_seeds_demo_merchants() -> None:
    container = build_container()
    assert container.merchants.get_by_short_code("1001") is not None
    assert {m.id for m in container.merchants.all()} == {"m_alpha", "m_beta"}


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_container: all passed")
