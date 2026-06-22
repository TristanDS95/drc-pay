"""Airtel Money (DRC) on-net rail — a direct C2B collection straight to the merchant.

Implements the ``DirectCollectRail`` shape for same-network Airtel payments. Researched API shape
(see ``drc-mvp-research/02-findings/cross-cutting/on-net-direct-operator-apis.md``):
  - Airtel Africa Open API "Collection" / request-to-pay; OAuth2 client-credentials Bearer; a
    USSD/PIN push prompts the customer; funds route to the merchant; the outcome arrives via a
    callback to our registered URL, with a GET status-enquiry as a reliable fallback (callback +
    poll double-check, like pawaPay).
  - **Self-serve SANDBOX at openapiuat.airtel.africa** — this is the one we can test today, so it is
    the recommended first integration.
  - Flow: POST /auth/oauth2/token → POST /merchant/v1/payments/ → callback / GET /standard/v1/payments/{id}.

⚠ NOT YET WIRED. Endpoint paths are from community SDKs (the DRC API reference is login-gated); the
aggregator/multi-merchant model and DRC production activation are unconfirmed. Validate against
openapiuat.airtel.africa before enabling.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...domains.ledger.money import Money

# TODO(sandbox): confirm against openapiuat.airtel.africa for the DRC ("CD") country.
_TOKEN_PATH = "/auth/oauth2/token"  # OAuth2 client_credentials → Bearer
_COLLECT_PATH = "/merchant/v1/payments/"  # initiate a collection (USSD push to the customer)


@dataclass
class AirtelConfig:
    base_url: str  # e.g. https://openapiuat.airtel.africa (sandbox) → https://openapi.airtel.africa (prod)
    client_id: str
    client_secret: str
    callback_url: str  # our registered URL Airtel POSTs the result to
    country: str = "CD"  # DRC


class AirtelOnNetRail:
    """On-net C2B rail for Airtel Money DRC. Initiates a direct collection to the merchant; the
    result arrives via the registered callback (with a status enquiry as backstop)."""

    def __init__(self, config: AirtelConfig) -> None:
        self._config = config

    def request_direct_collection(
        self, *, transaction_id: str, payer_msisdn: str, merchant_msisdn: str, amount: Money, provider: str
    ) -> str | None:
        # Intended request (validate field names against the sandbox before enabling):
        _request = {
            "reference": transaction_id,
            "subscriber": {"country": self._config.country, "msisdn": payer_msisdn},
            # TODO: confirm how the merchant recipient is named (merchant id vs msisdn) on-net.
            "merchant": merchant_msisdn,
            "transaction": {"amount": amount.to_major_str(), "currency": amount.currency, "id": transaction_id},
            "provider": provider,
            "target": f"{self._config.base_url}{_COLLECT_PATH}",
            "token_endpoint": f"{self._config.base_url}{_TOKEN_PATH}",
        }
        raise NotImplementedError(
            "Airtel on-net rail not yet wired — OAuth2 (client_credentials) then POST the above to the "
            "Collection endpoint; persist the txn id and resolve via callback + status enquiry. "
            f"Validate against openapiuat.airtel.africa (self-serve sandbox). request={_request}"
        )
