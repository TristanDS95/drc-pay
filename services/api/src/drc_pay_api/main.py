"""FastAPI application factory.

Thin HTTP layer: routing, middleware, and serialization only. All money logic lives
in ``drc_pay_api.domains``, framework-agnostic, so the same core can later be driven
by the USSD gateway without reimplementation.

``create_app()`` builds a fresh application (with its own in-memory wiring), so tests
spin up isolated instances. The module-level ``app`` is what uvicorn serves.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .http.container import build_container
from .http.demo_routes import demo_router
from .http.merchant_routes import merchant_router
from .http.routes import router
from .http.ussd_routes import ussd_router
from .http.webhook_routes import webhook_router
from .ussd.session import UssdHandler


def create_app() -> FastAPI:
    app = FastAPI(title="DRC Pay — Merchant Acquiring API", version="0.0.1")

    # DEV ONLY: let the local web Merchant Console (a different origin) call the API.
    # Production locks this down to known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.container = build_container(
        database_url=settings.database_url,
        pawapay_base_url=settings.pawapay_base_url,
        pawapay_api_token=settings.pawapay_api_token,
        ussd_shortcode=settings.ussd_shortcode,
        pawapay_public_key=settings.pawapay_public_key,
        environment=settings.environment,
    )
    # The USSD channel is another thin caller into the same container/orchestrator.
    app.state.ussd_handler = UssdHandler(app.state.container)
    app.include_router(router)
    app.include_router(merchant_router)
    app.include_router(ussd_router)
    app.include_router(webhook_router)
    # Demo/ops controls (e.g. trigger reconciliation) — mounted off the real-money path only
    # (simulator or sandbox), never in production. See Container.demo_controls_enabled.
    if app.state.container.demo_controls_enabled:
        app.include_router(demo_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
