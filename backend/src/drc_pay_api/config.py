"""Configuration via environment variables (12-factor).

Nothing secret is hard-coded. Sandbox vs production is selected purely by which
environment variables are present — there is no code path that mixes them.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRCPAY_", env_file=".env", extra="ignore")

    environment: str = "local"  # local | sandbox | production

    database_url: str = ""

    # pawaPay — base URL + token are set per environment from pawaPay's docs and the
    # secret store. No default URL here, so we never accidentally point at the wrong one.
    pawapay_base_url: str = ""
    pawapay_api_token: str = ""
    # pawaPay's public key (PEM) for verifying signed callbacks (RFC-9421 / ECDSA-P256).
    # Blank in the demo → the webhook receiver rejects everything when no live rail is set.
    pawapay_public_key: str = ""

    # Reconciliation sweep: how often (seconds) the background job polls pawaPay for missed
    # deposit/payout/refund outcomes. Runs only on a live rail (never the in-process simulator).
    reconcile_interval_seconds: int = 300

    # USSD shortcode the customer dials (e.g. *123#); each merchant's till is appended
    # (*123*1001#). The real code is assigned by the USSD aggregator/operator — this is a
    # placeholder until it's provisioned.
    ussd_shortcode: str = "*123#"
    # Menu language for the USSD channel: "fr" (default — the DRC's primary language) or "en".
    # A deployment-level default, not an in-menu step: every extra step costs completion.
    ussd_lang: str = "fr"
    # Shared secret the USSD aggregator must send in X-USSD-Secret. Blank disables the check
    # (local/sandbox, where the console's dial simulator drives /ussd from the browser);
    # production REFUSES TO BOOT without it — see create_app.
    ussd_shared_secret: str = ""

    # Hosting (a deployed sandbox demo). When CONSOLE_DIR is set, the app also serves the
    # static Merchant Console from that directory, same-origin with the API. When
    # BASIC_AUTH_PASSWORD is set, every request is gated behind HTTP Basic auth (username
    # ``drcpay``, this password) EXCEPT the pawaPay webhook and the health probe. Both blank
    # in local dev → console served separately, no auth.
    console_dir: str = ""
    basic_auth_password: str = ""
    # The public customer-facing pages (scan-to-pay + USSD dial simulator) — served when set,
    # and NOT behind the password (a customer who scans a QR has no login).
    customer_dir: str = ""


settings = Settings()
