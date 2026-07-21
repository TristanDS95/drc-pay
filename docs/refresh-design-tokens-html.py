#!/usr/bin/env python3
"""Refresh the embedded design-tokens.md snapshot inside design-tokens.html.

design-tokens.md is the single source of truth. design-tokens.html renders it, and carries
an embedded snapshot between the TOKENS-MD:BEGIN/END markers so the page also works when
double-clicked (file://), where browsers block fetching a sibling file. Run this after
editing design-tokens.md:

    python3 docs/refresh-design-tokens-html.py
"""

from pathlib import Path

DOCS = Path(__file__).resolve().parent
md = (DOCS / "design-tokens.md").read_text(encoding="utf-8")
html = (DOCS / "design-tokens.html").read_text(encoding="utf-8")

BEGIN = "<!-- TOKENS-MD:BEGIN"
END = "<!-- TOKENS-MD:END -->"

if "</script" in md.lower():
    raise SystemExit("design-tokens.md contains a </script sequence; cannot embed safely.")

start = html.index(BEGIN)
stop = html.index(END, start) + len(END)

# Embed the markdown flush-left (the renderer's intro/section detection keys off
# unindented '#' and '|' line starts).
block = (
    "<!-- TOKENS-MD:BEGIN - generated snapshot of design-tokens.md; "
    "refresh via docs/refresh-design-tokens-html.py -->\n"
    '<script type="text/markdown" id="tokens-md">\n'
    f"{md.rstrip(chr(10))}\n"
    "</script>\n"
    "<!-- TOKENS-MD:END -->"
)

(DOCS / "design-tokens.html").write_text(html[:start] + block + html[stop:], encoding="utf-8")
print(f"Embedded {len(md)} chars of design-tokens.md into design-tokens.html")
