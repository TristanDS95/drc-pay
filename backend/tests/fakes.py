"""Test doubles for the orchestrator.

The in-memory store and ledger are the real adapters from ``drc_pay_api.adapters``
(no need to duplicate them here). This module provides ``FakePaymentRail``, which
records requests (with the provider) so a test can assert on them and returns synthetic
op-ids the orchestrator should persist, plus ``FakePredictor`` for the route's
provider-resolution path. Outcomes are delivered via the orchestrator's ``on_*_result``.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.ports import RailRejected
from drc_pay_api.integrations.pawapay.client import ProviderPrediction


class FakePaymentRail:
    def __init__(self, reject_legs: set[str] | None = None) -> None:
        self.collections: list[tuple[str, str, Money, str]] = []
        self.payouts: list[tuple[str, str, Money, str]] = []
        self.refunds: list[tuple[str, str | None, Money]] = []
        # Legs to reject *synchronously* (collection / payout / refund) — for testing the
        # RailRejected path that maps a provider's immediate rejection to a leg failure.
        self._reject = reject_legs or set()

    def request_collection(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.collections.append((transaction_id, msisdn, amount, provider))
        if "collection" in self._reject:
            raise RailRejected("collection rejected (fake)")
        return f"dep-{transaction_id}"

    def request_payout(
        self, *, transaction_id: str, msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.payouts.append((transaction_id, msisdn, amount, provider))
        if "payout" in self._reject:
            raise RailRejected("payout rejected (fake)")
        return f"pay-{transaction_id}"

    def request_refund(
        self, *, transaction_id: str, deposit_id: str | None, amount: Money, provider: str
    ) -> str | None:
        self.refunds.append((transaction_id, deposit_id, amount))
        if "refund" in self._reject:
            raise RailRejected("refund rejected (fake)")
        return f"ref-{transaction_id}"


class FakeDirectRail:
    """Stands in for an operator's on-net C2B rail (M-Pesa / Airtel). Records each direct
    collection and returns a synthetic op-id; outcomes are delivered via OnNetOrchestrator.on_confirm.
    ``reject=True`` exercises the synchronous-rejection path."""

    def __init__(self, reject: bool = False) -> None:
        self.collections: list[tuple[str, str, str, Money, str]] = []
        self._reject = reject

    def request_direct_collection(
        self, *, transaction_id: str, payer_msisdn: str, merchant_msisdn: str, amount: Money, provider: str
    ) -> str | None:
        self.collections.append((transaction_id, payer_msisdn, merchant_msisdn, amount, provider))
        if self._reject:
            raise RailRejected("direct collection rejected (fake)")
        return f"onnet-{transaction_id}"


class FakePredictor:
    """Stands in for the pawaPay client's predict-provider in route tests."""

    def __init__(self, provider: str | None) -> None:
        self._provider = provider

    def predict_provider(self, phone_number: str) -> ProviderPrediction:
        return ProviderPrediction(provider=self._provider, phone_number=phone_number, country="COD")


def pawapay_keypair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """A fresh P-256 keypair; returns (private_key, public_key_pem) for signing tests."""
    sk = ec.generate_private_key(ec.SECP256R1())
    pem = sk.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return sk, pem


def sign_pawapay_callback(
    private_key: ec.EllipticCurvePrivateKey, *, host: str, path: str, body: bytes, created: int
) -> dict[str, str]:
    """Produce RFC-9421 callback headers the way pawaPay signs them (P-256), for tests."""
    content_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    params = (
        '("@method" "@authority" "@path" "content-digest")'
        f';created={created};keyid="pawapay";alg="ecdsa-p256-sha256"'
    )
    base = "\n".join([
        '"@method": POST',
        f'"@authority": {host.lower()}',
        f'"@path": {path}',
        f'"content-digest": {content_digest}',
        f'"@signature-params": {params}',
    ])
    r, s = decode_dss_signature(private_key.sign(base.encode(), ec.ECDSA(hashes.SHA256())))
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return {
        "Content-Digest": content_digest,
        "Signature-Input": f"sig1={params}",
        "Signature": f"sig1=:{base64.b64encode(raw).decode()}:",
    }
