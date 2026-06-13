"""Test environment isolation.

A developer's local ``services/api/.env`` may hold real pawaPay **sandbox credentials**. Without
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
