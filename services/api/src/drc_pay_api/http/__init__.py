"""HTTP layer — routes and middleware.

To build. A thin caller into the domain services. Middleware: idempotency-key
handling, rate limiting, JWT auth. No money logic lives here.
"""
