"""M-Pesa (Vodacom DRC) on-net rail — a direct C2B collection straight to the merchant.

Implements the ``DirectCollectRail`` shape for same-network M-Pesa payments. Researched API shape
(see ``drc-mvp-research/02-findings/cross-cutting/on-net-direct-operator-apis.md``):
  - Vodacom M-Pesa "C2B Single Payment" via the OpenAPI portal (openapiportal.m-pesa.com); DRC is a
    supported market. A USSD/STK push prompts the customer; on PIN entry, funds route to the
    merchant's ServiceProviderCode in one leg; the final outcome arrives as an async callback to our
    Response URL.
  - Auth: API key + public key → an encrypted session token (Bearer).
  - Flow: POST /getSession → POST /ipg/v2/<DRC-market>/c2bPayment/singleStage/ → async callback.

⚠ NOT YET WIRED. The DRC market-code path segment, the exact field names, the IP-whitelisting and the
business-account onboarding are partner-gated and unconfirmed in public docs. Validate against the
OpenAPI portal sandbox (and confirm whether one credential can serve many merchant short codes — the
aggregator model) before enabling. Do not assume the endpoints below are correct until tested.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...domains.ledger.money import Money

# TODO(sandbox): confirm these against the M-Pesa OpenAPI portal for the DRC market.
_SESSION_PATH = "/getSession/"  # exchange API key + public key → a Bearer session token
_C2B_PATH = "/ipg/v2/{market}/c2bPayment/singleStage/"  # the DRC market-code segment is unconfirmed


@dataclass
class MpesaConfig:
    base_url: str
    api_key: str
    public_key: str
    market: str  # the DRC market-code path segment for ``_C2B_PATH`` (TODO: confirm)
    response_url: str  # our public callback endpoint M-Pesa POSTs the result to


class MpesaOnNetRail:
    """On-net C2B rail for Vodacom M-Pesa DRC. Initiates a direct collection to the merchant's short
    code; the result arrives later via the configured Response URL callback → ``OnNetOrchestrator``."""

    def __init__(self, config: MpesaConfig) -> None:
        self._config = config

    def request_direct_collection(
        self, *, transaction_id: str, payer_msisdn: str, merchant_msisdn: str, amount: Money, provider: str
    ) -> str | None:
        # Intended request (validate field names against the sandbox before enabling):
        _request = {
            "Amount": amount.to_major_str(),
            "Currency": amount.currency,
            "CustomerMSISDN": payer_msisdn,
            # TODO: M-Pesa identifies the merchant by ServiceProviderCode (their till short code),
            # not their msisdn — resolve it from the merchant before sending.
            "ServiceProviderCode": merchant_msisdn,
            "ThirdPartyConversationID": transaction_id,
            "TransactionReference": transaction_id,
            "provider": provider,
            "target": f"{self._config.base_url}{_C2B_PATH.format(market=self._config.market)}",
        }
        raise NotImplementedError(
            "M-Pesa on-net rail not yet wired — do a getSession, POST the above to the C2B endpoint, "
            "and persist output_ConversationID (the op-id); the outcome lands on the Response URL. "
            f"Validate against the OpenAPI sandbox first (see on-net-direct-operator-apis.md). "
            f"request={_request}"
        )
