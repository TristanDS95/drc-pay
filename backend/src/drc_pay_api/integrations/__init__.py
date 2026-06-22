"""Integrations — boundaries to external systems.

Each external system is wrapped behind an interface so the rest of the app depends on
*our* shape, not the vendor's, and so a local fake can stand in for tests.
"""
