"""Adapters — concrete implementations of the domain ports.

These fill the slots the domain defines (``domains.transactions.ports``) with real
infrastructure. ``memory`` holds in-process implementations used for local dev and the
built-in simulator; Postgres-backed versions replace them for production.
"""
