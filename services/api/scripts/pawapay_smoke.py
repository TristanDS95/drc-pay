"""Read-only pawaPay sandbox connectivity check — proves the API token authenticates,
without moving any money.

Reads DRCPAY_PAWAPAY_BASE_URL / DRCPAY_PAWAPAY_API_TOKEN from the environment, calls pawaPay's
GET /v2/active-conf (a read-only config endpoint), and prints only the HTTP status — never the
token itself.

Run from services/api with the venv active:
    set -a; source .env; set +a          # load the local .env into the environment
    python scripts/pawapay_smoke.py
"""
from __future__ import annotations

import os

import httpx


def main() -> int:
    base = os.environ.get("DRCPAY_PAWAPAY_BASE_URL", "").rstrip("/")
    token = os.environ.get("DRCPAY_PAWAPAY_API_TOKEN", "")
    if not base or not token:
        print("✗ DRCPAY_PAWAPAY_BASE_URL / DRCPAY_PAWAPAY_API_TOKEN are not set.")
        print("  Put the token in services/api/.env, then:  set -a; source .env; set +a")
        return 1

    url = f"{base}/v2/active-conf"
    print(f"→ GET {url}   (token present: {len(token)} chars, redacted)")
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)
    except httpx.HTTPError as exc:
        print(f"✗ Network error reaching pawaPay: {exc}")
        return 1

    print(f"← HTTP {resp.status_code}")
    if resp.status_code == 200:
        print("✓ Connected — your sandbox token authenticates against pawaPay. No money moved.")
        return 0
    if resp.status_code in (401, 403):
        print("✗ Token rejected — re-check the sandbox API token pasted into services/api/.env.")
    else:
        print(f"✗ Unexpected response. First 300 chars of the body:\n{resp.text[:300]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
