"""fabricgate list command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from fabricgate.client.cache import load_index


@click.command(name="list")
@click.pass_obj
def list_cmd(obj: dict[str, object]) -> None:
    """List cached designs."""
    cache_dir = Path(str(obj["cache_dir"]))
    index = load_index(cache_dir)

    if obj["json"]:
        click.echo(json.dumps([e.model_dump(mode="json") for e in index.entries], indent=2))
        return

    if not index.entries:
        click.echo("No cached designs.")
        return

    # Build table rows
    rows: list[tuple[str, str, str, str]] = []
    for entry in index.entries:
        pulled = entry.pulled_at.strftime("%Y-%m-%d")
        rows.append((entry.name, entry.version, entry.platform, pulled))

    # Column widths
    headers = ("DESIGN", "VERSION", "PLATFORM", "PULLED")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    click.echo(fmt.format(*headers))
    for row in rows:
        click.echo(fmt.format(*row))
