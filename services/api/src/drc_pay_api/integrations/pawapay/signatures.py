"""Verify pawaPay's signed callbacks: RFC-9421 HTTP Message Signatures over an RFC-9530
Content-Digest, using pawaPay's public key (ECDSA P-256 / SHA-256).

pawaPay signs callbacks with a **public-key** signature (not HMAC). We verify:
  1. the ``Content-Digest`` header matches the raw body (binds the body to the signature),
  2. the RFC-9421 signature over the reconstructed signature base verifies against
     pawaPay's public key, and
  3. the signature is fresh (the ``created`` parameter is within a small window).

Anything missing, malformed, stale, tampered, or unverifiable raises ``SignatureError``.

⚠️ Provisional: this implements the ``ecdsa-p256-sha256`` profile of RFC-9421 for the
component set pawaPay is expected to cover (``@method``, ``@authority``, ``@path``,
``content-digest``), but it is driven by the *received* ``Signature-Input``, so it adapts
to whatever components pawaPay actually signs. The exact covered components and header
casing must be confirmed against real sandbox callbacks (Phase E).
Source: https://docs.pawapay.io/v2/docs/signatures
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections.abc import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

_MAX_AGE_SECONDS = 300
_DIGESTS: dict[str, Callable[[bytes], "hashlib._Hash"]] = {
    "sha-256": hashlib.sha256,
    "sha-512": hashlib.sha512,
}


class SignatureError(Exception):
    """A callback's signature is missing, malformed, stale, or does not verify."""


def _get(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    raise SignatureError(f"missing header: {name}")


def _check_content_digest(content_digest: str, raw_body: bytes) -> None:
    match = re.match(r"\s*([A-Za-z0-9-]+)=:([^:]+):\s*$", content_digest)
    if not match:
        raise SignatureError("malformed Content-Digest")
    algorithm = match.group(1).lower()
    digest_fn = _DIGESTS.get(algorithm)
    if digest_fn is None:
        raise SignatureError(f"unsupported Content-Digest algorithm: {algorithm}")
    expected = base64.b64encode(digest_fn(raw_body).digest()).decode()
    if not hmac.compare_digest(expected, match.group(2)):
        raise SignatureError("Content-Digest does not match the body")


def _component_value(
    component: str, *, method: str, host: str, path: str, headers: Mapping[str, str]
) -> str:
    if component == "@method":
        return method.upper()
    if component == "@authority":
        return host.lower()
    if component == "@path":
        return path
    if component.startswith("@"):
        raise SignatureError(f"unsupported derived component: {component}")
    return _get(headers, component).strip()  # a literal header field


def _build_signature_base(
    covered: list[str],
    params_value: str,
    *,
    method: str,
    host: str,
    path: str,
    headers: Mapping[str, str],
) -> str:
    lines = [
        f'"{c}": {_component_value(c, method=method, host=host, path=path, headers=headers)}'
        for c in covered
    ]
    lines.append(f'"@signature-params": {params_value}')
    return "\n".join(lines)


def _parse_signature_input(value: str) -> tuple[str, list[str], str, dict[str, str]]:
    match = re.match(r"\s*([A-Za-z0-9_-]+)=(\((?P<list>[^)]*)\)(?P<params>[^\n]*?))\s*$", value)
    if not match:
        raise SignatureError("malformed Signature-Input")
    label = match.group(1)
    params_value = match.group(2)  # the full "(...);params" — the @signature-params value
    covered = [tok.strip().strip('"') for tok in match.group("list").split() if tok.strip()]
    if not covered:
        raise SignatureError("Signature-Input lists no components")
    params = {k: v for k, _q, v in re.findall(r';([a-z]+)=("?)([^";]+)\2', match.group("params"))}
    return label, covered, params_value, params


def _parse_signature(value: str, label: str) -> bytes:
    match = re.search(re.escape(label) + r"=:([^:]+):", value)
    if not match:
        raise SignatureError("malformed Signature header")
    return base64.b64decode(match.group(1))


def verify_pawapay_signature(
    *,
    public_key_pem: str,
    method: str,
    path: str,
    host: str,
    headers: Mapping[str, str],
    raw_body: bytes,
    now: int,
) -> None:
    """Raise ``SignatureError`` unless the callback is correctly signed and fresh. ``now``
    is the current epoch seconds (injected so the freshness check is testable)."""
    if not public_key_pem:
        raise SignatureError("no pawaPay public key configured")

    _check_content_digest(_get(headers, "content-digest"), raw_body)

    label, covered, params_value, params = _parse_signature_input(_get(headers, "signature-input"))
    created = params.get("created")
    if created is None or not created.isdigit():
        raise SignatureError("missing or invalid `created` parameter")
    if abs(now - int(created)) > _MAX_AGE_SECONDS:
        raise SignatureError("signature timestamp is stale or in the future")

    signature_base = _build_signature_base(
        covered, params_value, method=method, host=host, path=path, headers=headers
    )
    raw_sig = _parse_signature(_get(headers, "signature"), label)
    if len(raw_sig) != 64:
        raise SignatureError("unexpected signature length (expected 64 bytes for P-256)")

    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
    except Exception as exc:
        raise SignatureError("could not load pawaPay public key") from exc
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise SignatureError("pawaPay public key is not an EC key")

    der = encode_dss_signature(
        int.from_bytes(raw_sig[:32], "big"), int.from_bytes(raw_sig[32:], "big")
    )
    try:
        public_key.verify(der, signature_base.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise SignatureError("signature does not verify") from exc
