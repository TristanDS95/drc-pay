"""Merchant endpoints: the customer-facing payment codes (USSD string / tel URI). Uses the seeded
demo merchants (m_alpha till 1001, m_beta till 1002).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.application.payment_codes import merchant_payment_code
from drc_pay_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_payment_code_builds_ussd_and_tel_uri() -> None:
    code = merchant_payment_code("*123#", "1001")
    assert code.ussd_string == "*123*1001#"
    assert code.tel_uri == "tel:*123*1001%23"  # '#' percent-encoded for the QR/dialer


def test_list_merchants_exposes_codes() -> None:
    body = _client().get("/merchants").json()
    by_id = {m["id"]: m for m in body}
    assert by_id["m_alpha"]["ussd_string"] == "*123*1001#"
    assert by_id["m_alpha"]["tel_uri"] == "tel:*123*1001%23"
    assert by_id["m_beta"]["ussd_string"] == "*123*1002#"


def test_get_merchant() -> None:
    body = _client().get("/merchants/m_alpha").json()
    assert body["name"] == "Alpha Gas Station"
    assert body["ussd_string"] == "*123*1001#"


def test_get_unknown_merchant_404() -> None:
    assert _client().get("/merchants/nope").status_code == 404


def test_merchant_ussd_qr_svg() -> None:
    # The printable static-till USSD sticker (encodes the tel: dial-through).
    qr = _client().get("/merchants/m_alpha/qr.svg")
    assert qr.status_code == 200
    assert "image/svg" in qr.headers["content-type"]
    assert qr.content.startswith(b"<?xml") or qr.content.lstrip().startswith(b"<svg")


def test_merchant_ussd_qr_unknown_404() -> None:
    assert _client().get("/merchants/nope/qr.svg").status_code == 404


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_merchants: all passed")
