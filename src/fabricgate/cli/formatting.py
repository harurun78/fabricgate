"""Output formatting shared by CLI commands."""

from __future__ import annotations


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
