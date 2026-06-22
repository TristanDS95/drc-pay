"""The on-net vs routed decision: same-network + a rail → direct; otherwise pawaPay."""
from __future__ import annotations

from drc_pay_api.application.routing import use_on_net

# Operators we have an in-app on-net rail for. Orange is excluded (redirect/OTP, no in-app push).
ON_NET = frozenset({"VODACOM_MPESA_COD", "AIRTEL_COD"})


def test_same_network_with_a_rail_goes_direct() -> None:
    assert use_on_net("AIRTEL_COD", "AIRTEL_COD", ON_NET) is True
    assert use_on_net("VODACOM_MPESA_COD", "VODACOM_MPESA_COD", ON_NET) is True


def test_cross_network_routes_through_pawapay() -> None:
    assert use_on_net("AIRTEL_COD", "VODACOM_MPESA_COD", ON_NET) is False


def test_same_network_without_a_rail_falls_back_to_pawapay() -> None:
    # Orange is same-network but has no in-app on-net rail → fall back to pawaPay.
    assert use_on_net("ORANGE_COD", "ORANGE_COD", ON_NET) is False
