"""The two gates and how they divide the surface:

- **Merchant sessions** (per-merchant login) gate the merchant API in EVERY environment —
  see ``test_auth.py`` for the full auth behavior.
- **The shared Basic password** gates only the sandbox demo SHELL (console static files,
  docs, demo endpoints). It never gates the merchant API, the webhook, health, or the
  customer paths. Off when unset (local dev / tests / production).
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.main import create_app

from conftest import as_merchant


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_merchant_api_is_session_gated_even_with_no_password() -> None:
    assert config.settings.basic_auth_password == ""  # default: no demo gate
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/transactions").status_code == 401  # session required, always
    assert as_merchant(client).get("/transactions").status_code == 200


def test_password_gates_the_demo_shell_not_the_merchant_api(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "basic_auth_password", "sesame")
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200  # health stays open for the platform probe

    # The demo shell (docs here) is Basic-gated: 401 without, 200 with the right password.
    blocked = client.get("/docs")
    assert blocked.status_code == 401
    assert blocked.headers.get("www-authenticate", "").startswith("Basic")
    assert client.get("/docs", headers=_basic("drcpay", "sesame")).status_code == 200
    assert client.get("/docs", headers=_basic("drcpay", "nope")).status_code == 401
    assert client.get("/docs", headers=_basic("admin", "sesame")).status_code == 401

    # The merchant API is NOT behind the shared password — it answers to the session alone
    # (each merchant has their own login; a shared password would defeat per-merchant auth).
    no_session = client.get("/transactions")
    assert no_session.status_code == 401
    assert no_session.headers.get("www-authenticate", "").startswith("Bearer")
    assert as_merchant(client).get("/transactions").status_code == 200  # no Basic needed


def test_signup_is_public_not_behind_the_demo_gate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Merchant self-onboarding must work without the sandbox demo password — a business
    registering itself has no such password. /signup only ever creates a PENDING merchant,
    which can't act until an admin approves it, so exempting it gives up nothing."""
    monkeypatch.setattr(config.settings, "basic_auth_password", "sesame")
    client = TestClient(create_app())
    response = client.post(
        "/signup",
        json={
            "name": "Public Signup Co",
            "settlement_msisdn": "243973456712",
            "username": "publicsignup",
            "password": "open-signup-1234",
        },
    )
    assert response.status_code == 201, response.text  # reached the handler, not Basic-blocked
    assert response.json()["status"] == "pending"


def test_demo_credentials_exempt_but_demo_shell_gated(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The login page's chips fetch /demo/credentials in the background; some browsers don't
    # attach Basic credentials to fetch(). Exempting it reveals nothing an outsider can't
    # already use (public /auth/login + documented demo passwords). Reconcile stays gated.
    monkeypatch.setattr(config.settings, "basic_auth_password", "sesame")
    client = TestClient(create_app())
    assert client.get("/demo/credentials").status_code == 200
    assert client.post("/demo/reconcile").status_code == 401


def test_cache_discipline_headers() -> None:
    # Browsers heuristically cached the console page and kept running OLD code across
    # reloads - stale pages spoke a header protocol the server no longer had. The HTML
    # shell must always revalidate; auth/API responses must never be cached at all.
    client = as_merchant(TestClient(create_app()))
    assert client.get("/transactions").headers.get("cache-control") == "no-store"
    assert client.get("/auth/me").headers.get("cache-control") == "no-store"


def test_sandbox_refuses_to_boot_without_a_password(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The sandbox's demo shell is meant to be gated, and the Basic gate fails OPEN when no
    # password is set — so a sandbox without one must refuse to start. (Production instead
    # requires a database and gates the merchant API by session; the shared password is
    # optional there by design.)
    monkeypatch.setattr(config.settings, "environment", "sandbox")
    monkeypatch.setattr(config.settings, "basic_auth_password", "")
    with pytest.raises(RuntimeError, match="BASIC_AUTH_PASSWORD"):
        create_app()


def _run_all() -> None:
    _monkeypatched = {
        test_password_gates_the_demo_shell_not_the_merchant_api,
        test_sandbox_refuses_to_boot_without_a_password,
    }
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and fn not in _monkeypatched:
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_security: all passed (run via pytest for the monkeypatch tests)")
