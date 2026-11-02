"""Output formatting shared by CLI commands."""

from __future__ import annotations

import unicodedata


def sanitize(value: object) -> str:
    """Return *value* as text that is safe to print: control and format characters become ``?``.

    Publishers write much of what the registry returns (summaries, authors, tags, notes,
    yank reasons, artifact file names). Printed as is, escape sequences, bidi overrides and
    line breaks in it would reach the viewer's terminal, so text output passes
    registry-supplied strings through this. Spaces such as U+3000 are kept.
    ``--json`` output is escaped by the JSON encoder instead.
    """
    return "".join(ch if ch.isprintable() or unicodedata.category(ch) == "Zs" else "?" for ch in str(value))


def sanitize_lines(text: str) -> str:
    """:func:`sanitize` each line of *text*, keeping its line breaks (for multi-line messages)."""
    return "\n".join(sanitize(line) for line in text.split("\n"))


def format_size(value: int) -> str:
    """Return *value* bytes as ``"512 B"``, ``"256 KB"`` or ``"1.5 MB"`` (1024-based, up to TB)."""
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B" or size.is_integer():
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(value)} B"  # pragma: no cover
