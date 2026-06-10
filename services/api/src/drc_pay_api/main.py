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
from .http.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="DRC Pay API", version="0.0.1")

    # DEV ONLY: let the local web phone-mock (a different origin) call the API.
    # Production locks this down to known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.container = build_container()
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
