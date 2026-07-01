"""The hosted-demo shared-password gate (HTTP Basic auth). Off by default (local/tests);
when a password is set, every path is gated except the webhook + health probe.
"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.main import create_app


def _auth(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_no_password_means_no_gate() -> None:
    assert config.settings.basic_auth_password == ""  # default: API is open, as before
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/transactions").status_code == 200


def test_password_gates_the_api(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "basic_auth_password", "sesame")
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200  # health stays open for the platform probe
    blocked = client.get("/transactions")
    assert blocked.status_code == 401
    assert blocked.headers.get("www-authenticate", "").startswith("Basic")

    # Correct credentials (username "drcpay") pass; wrong password / user are rejected.
    assert client.get("/transactions", headers=_auth("drcpay", "sesame")).status_code == 200
    assert client.get("/transactions", headers=_auth("drcpay", "nope")).status_code == 401
    assert client.get("/transactions", headers=_auth("admin", "sesame")).status_code == 401


def test_deployed_env_refuses_to_boot_without_a_password(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The gate fails OPEN when no password is set, so a non-local env with none configured would
    # serve the merchant API unauthenticated. The app must refuse to start instead.
    monkeypatch.setattr(config.settings, "environment", "sandbox")
    monkeypatch.setattr(config.settings, "basic_auth_password", "")
    with pytest.raises(RuntimeError, match="BASIC_AUTH_PASSWORD"):
        create_app()


def _run_all() -> None:
    _monkeypatched = {test_password_gates_the_api, test_deployed_env_refuses_to_boot_without_a_password}
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and fn not in _monkeypatched:
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_security: all passed (run via pytest for the monkeypatch test)")
