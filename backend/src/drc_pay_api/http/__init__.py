"""HTTP layer — routes and middleware.

A thin caller into the domain services: routes validate input, delegate to an
``application/`` service, and serialize the result. No money logic lives here. The
composition root is the package-level ``drc_pay_api/container.py`` (every channel wires
through it); ``dependencies.py`` here is the FastAPI glue that injects it into routes.
The shared-password gate and CORS live in ``main.py``.
"""
