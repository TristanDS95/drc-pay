"""The Staff Console is served, and its shipped HTML holds the guarantees the Python suite
can't otherwise see (it renders no CSS/JS).

Two kinds of check:
- the app actually mounts the page at ``/staff`` when ``DRCPAY_STAFF_DIR`` is set, and does NOT
  when it isn't (local dev serves the frontends separately);
- cheap string assertions on the page itself: the hide utility must be authoritative (the same
  overlay collision that once broke the merchant console's login), and merchant-supplied values
  must be escaped before they reach innerHTML — anyone can sign up, so names are untrusted.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.main import create_app

STAFF = Path(__file__).resolve().parents[2] / "frontend" / "staff-console" / "index.html"


def test_staff_console_is_mounted_when_configured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "staff_dir", str(STAFF.parent))
    response = TestClient(create_app()).get("/staff/")
    assert response.status_code == 200
    assert "Staff Console" in response.text


def test_staff_console_is_absent_when_not_configured() -> None:
    # Default (tests force it blank): no mount, so the path 404s rather than serving a stray dir.
    assert config.settings.staff_dir == ""
    assert TestClient(create_app()).get("/staff/").status_code == 404


def test_hidden_utility_is_authoritative() -> None:
    assert ".hidden{display:none !important;}" in STAFF.read_text(), (
        "`.hidden` must use !important so it always overrides later same-specificity "
        "display rules (e.g. .loginwrap{display:flex})"
    )


def test_merchant_supplied_values_are_escaped() -> None:
    # Merchant name/number/till are user-supplied via public sign-up and rendered into innerHTML.
    html = STAFF.read_text()
    assert "const esc = (s) =>" in html, "the staff console must define an escaper"
    for field in ("m.name", "m.settlement_msisdn", "m.short_code", "m.id"):
        assert f"esc({field})" in html, f"{field} must be escaped before reaching innerHTML"


def test_rejected_rows_offer_a_re_approve_action() -> None:
    """Guards the fix for rejecting being a dead end. The Python suite can't run the page's JS, so
    assert the status-dependent action helper still handles 'rejected'."""
    html = STAFF.read_text()
    assert "function actionsFor(m)" in html, "actions must be chosen per merchant status"
    assert 'm.status === "rejected"' in html, "rejected rows must offer an action"
    assert "Re-approve" in html
