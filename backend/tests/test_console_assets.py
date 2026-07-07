"""Static guards on the merchant console's shipped HTML/CSS.

These catch regressions the Python suite otherwise can't see: it renders no CSS, so a
purely visual bug (like the `.hidden` overlay collision) passes every functional test
while the real page is broken. A cheap string assertion locks the fix in CI.
"""
from __future__ import annotations

from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[2] / "frontend" / "merchant-console" / "index.html"


def test_hidden_utility_is_authoritative() -> None:
    # The login overlay is `.loginwrap.hidden`, and `.loginwrap{display:flex}` is defined
    # later with equal specificity. Without !important on `.hidden`, the overlay stayed
    # visible over a fully-logged-in console — login "succeeded" but nothing appeared to
    # happen. The utility hide class must win regardless of source order.
    css = CONSOLE.read_text()
    assert ".hidden{display:none !important;}" in css, (
        "`.hidden` must use !important so it always overrides later same-specificity "
        "display rules (e.g. .loginwrap{display:flex})"
    )
