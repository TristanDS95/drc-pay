"""pawaPay callback signature verification (RFC-9421 / Content-Digest / ECDSA P-256).

The signing side here is built **independently** (the signature base is constructed by
hand, per the RFC, then signed with a freshly-generated P-256 key) so it genuinely
exercises the verifier rather than mirroring its internals.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from drc_pay_api.integrations.pawapay.signatures import SignatureError, verify_pawapay_signature

NOW = 1_700_000_100
CREATED = 1_700_000_000  # 100s before NOW → fresh
HOST = "api.drcpay.cd"
PATH = "/webhooks/pawapay"
BODY = b'{"depositId":"dep-1","status":"COMPLETED"}'


def _keypair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    sk = ec.generate_private_key(ec.SECP256R1())
    pem = sk.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return sk, pem


def _sign(
    sk: ec.EllipticCurvePrivateKey, *, body: bytes = BODY, created: int = CREATED, der: bool = False
) -> dict[str, str]:
    content_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    params = (
        '("@method" "@authority" "@path" "content-digest")'
        f';created={created};keyid="pawapay";alg="ecdsa-p256-sha256"'
    )
    base = "\n".join([
        '"@method": POST',
        f'"@authority": {HOST}',
        f'"@path": {PATH}',
        f'"content-digest": {content_digest}',
        f'"@signature-params": {params}',
    ])
    signature = sk.sign(base.encode(), ec.ECDSA(hashes.SHA256()))  # cryptography returns DER
    if der:
        sig_bytes = signature  # pawaPay's documented encoding
    else:
        r, s = decode_dss_signature(signature)
        sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big")  # RFC-9421 raw r‖s
    return {
        "Content-Digest": content_digest,
        "Signature-Input": f"sig1={params}",
        "Signature": f"sig1=:{base64.b64encode(sig_bytes).decode()}:",
    }


def _sign_pawapay(sk: ec.EllipticCurvePrivateKey, *, body: bytes = BODY, created: int = CREATED) -> dict[str, str]:
    """Sign exactly as pawaPay's v2 docs show: six covered components (incl. signature-date and
    content-type), the ``sig-pp`` label, an ``expires`` param, and a DER-encoded signature."""
    content_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    sig_date, content_type = "2025-05-15T07:38:56Z", "application/json"
    params = (
        '("@method" "@authority" "@path" "signature-date" "content-digest" "content-type")'
        f';created={created};keyid="CUSTOMER_TEST_KEY";alg="ecdsa-p256-sha256";expires={created + 60}'
    )
    base = "\n".join([
        '"@method": POST',
        f'"@authority": {HOST}',
        f'"@path": {PATH}',
        f'"signature-date": {sig_date}',
        f'"content-digest": {content_digest}',
        f'"content-type": {content_type}',
        f'"@signature-params": {params}',
    ])
    der = sk.sign(base.encode(), ec.ECDSA(hashes.SHA256()))  # cryptography returns DER
    return {
        "Content-Digest": content_digest,
        "Signature-Date": sig_date,
        "Content-Type": content_type,
        "Signature-Input": f"sig-pp={params}",
        "Signature": f"sig-pp=:{base64.b64encode(der).decode()}:",
    }


def _verify(pem: str, headers: dict[str, str], *, body: bytes = BODY, path: str = PATH, now: int = NOW) -> None:
    verify_pawapay_signature(
        public_key_pem=pem, method="POST", path=path, host=HOST,
        headers=headers, raw_body=body, now=now,
    )


def _rejects(fn: Callable[[], Any]) -> None:
    try:
        fn()
    except SignatureError:
        return
    raise AssertionError("expected SignatureError")


def test_valid_signature_verifies() -> None:
    sk, pem = _keypair()
    _verify(pem, _sign(sk))  # does not raise


def test_der_encoded_signature_verifies() -> None:
    # pawaPay sends a DER-encoded ECDSA signature (~70 bytes), not the RFC-9421 raw-64 form.
    sk, pem = _keypair()
    _verify(pem, _sign(sk, der=True))  # does not raise


def test_pawapay_documented_callback_shape_verifies() -> None:
    # The full v2 shape: six covered components (sig-pp label, signature-date + content-type),
    # an expires param, and a DER signature — the verifier must accept it end-to-end.
    sk, pem = _keypair()
    _verify(pem, _sign_pawapay(sk))  # does not raise


def test_der_signature_wrong_key_rejected() -> None:
    sk, _ = _keypair()
    _, other_pem = _keypair()
    _rejects(lambda: _verify(other_pem, _sign_pawapay(sk)))


def test_tampered_body_rejected() -> None:
    sk, pem = _keypair()
    headers = _sign(sk)
    _rejects(lambda: _verify(pem, headers, body=BODY + b" "))  # Content-Digest mismatch


def test_wrong_key_rejected() -> None:
    sk, _ = _keypair()
    _, other_pem = _keypair()
    _rejects(lambda: _verify(other_pem, _sign(sk)))


def test_changed_path_rejected() -> None:
    sk, pem = _keypair()
    _rejects(lambda: _verify(pem, _sign(sk), path="/somewhere-else"))  # base no longer matches


def test_stale_timestamp_rejected() -> None:
    sk, pem = _keypair()
    _rejects(lambda: _verify(pem, _sign(sk), now=CREATED + 10_000))  # well outside the window


def test_missing_signature_header_rejected() -> None:
    sk, pem = _keypair()
    headers = _sign(sk)
    del headers["Signature"]
    _rejects(lambda: _verify(pem, headers))


def test_no_public_key_rejected() -> None:
    sk, _ = _keypair()
    _rejects(lambda: _verify("", _sign(sk)))


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_pawapay_signatures: all passed")
