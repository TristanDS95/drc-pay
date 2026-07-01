"""HTTP layer — routes and middleware.

A thin caller into the domain services: routes validate input, delegate to an
``application/`` service, and serialize the result. No money logic lives here. The
composition root is ``container.py``; the shared-password gate and CORS live in
``main.py``.
"""
