"""FastAPI dependency glue for the composition root.

The :class:`~drc_pay_api.container.Container` itself is framework-agnostic and lives at
package level (``drc_pay_api/container.py``) because every channel wires through it; this
module is the HTTP-only shim that hands it to routes via dependency injection.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..container import Container


def get_container(request: Request) -> Container:
    """The shared :class:`Container`, built once at startup and kept on ``app.state``."""
    container: Container = request.app.state.container
    return container


# FastAPI dependency: a route writes ``container: ContainerDep`` and FastAPI injects the shared
# container — replacing the per-file ``_container(request)`` helper that used to be copy-pasted.
ContainerDep = Annotated[Container, Depends(get_container)]
