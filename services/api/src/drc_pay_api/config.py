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
    redis_url: str = ""

    # pawaPay — base URL + token are set per environment from pawaPay's docs and the
    # secret store. No default URL here, so we never accidentally point at the wrong one.
    pawapay_base_url: str = ""
    pawapay_api_token: str = ""


settings = Settings()
