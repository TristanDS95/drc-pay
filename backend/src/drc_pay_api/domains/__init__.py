"""Domain layer — the framework- and channel-agnostic core of the product.

Nothing in here may import FastAPI, the database driver, or pawaPay's wire format.
These modules are the reusable heart that both the HTTP API and the future USSD
gateway call into.
"""
