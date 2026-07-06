"""Test environment isolation.

A developer's local ``backend/.env`` may hold real pawaPay **sandbox credentials**. Without
this, pydantic-settings would read that file and the suite would build a *live* rail and make
real network calls — violating our "offline and deterministic" rule (and separating sandbox
from test, always). os.environ takes precedence over the .env file, so forcing these empty/clean
here pins every ``create_app()`` test to the in-process simulator, regardless of .env.

Tests that need a live/sandbox/production container construct one explicitly instead.
"""
import os

# Force the credential-bearing vars empty (→ simulator) and the environment to a known value,
# overriding anything in a local .env. Must run before drc_pay_api.config is imported.
os.environ["DRCPAY_PAWAPAY_BASE_URL"] = ""
os.environ["DRCPAY_PAWAPAY_API_TOKEN"] = ""
os.environ["DRCPAY_PAWAPAY_PUBLIC_KEY"] = ""
os.environ["DRCPAY_DATABASE_URL"] = ""
os.environ["DRCPAY_ENVIRONMENT"] = "local"
# Hosting vars too — so tests never gate behind a password or try to mount a console dir.
os.environ["DRCPAY_BASIC_AUTH_PASSWORD"] = ""
os.environ["DRCPAY_CONSOLE_DIR"] = ""
os.environ["DRCPAY_CUSTOMER_DIR"] = ""

from typing import Any  # noqa: E402


def as_merchant(client: Any, username: str = "alpha", password: str | None = None) -> Any:
    """Log the TestClient in as a (seeded demo) merchant and attach the session to its default
    headers, so every subsequent call is authenticated. The merchant API is session-gated in
    every environment — tests exercise the same auth path production runs.

    Demo logins (seed.py): alpha / beta / gamma, password ``<username>-demo``.
    """
    response = client.post(
        "/auth/login", json={"username": username, "password": password or f"{username}-demo"}
    )
    assert response.status_code == 200, f"demo login failed: {response.text}"
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client
