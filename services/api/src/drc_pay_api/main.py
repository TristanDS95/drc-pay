"""FastAPI application entrypoint.

Thin HTTP layer: routing, middleware, and serialization only. All money logic lives
in ``drc_pay_api.domains``, framework-agnostic, so the same core can later be driven
by the USSD gateway without reimplementation.
"""
from __future__ import annotations

from fastapi import FastAPI

from .config import settings

app = FastAPI(title="DRC Pay API", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "environment": settings.environment}
