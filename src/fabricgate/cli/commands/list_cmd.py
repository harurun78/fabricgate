"""fabricgate list command."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.client.cache import load_index
from fabricgate.sdk import api as sdk_api


def _echo_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    click.echo(fmt.format(*headers))
    for row in rows:
        click.echo(fmt.format(*row))


@click.command(name="list")
@click.option("--remote", is_flag=True, help="List designs on the registry instead of the local cache.")
@click.option("--namespace", default=None, help="Namespace to list (remote). Defaults to your authenticated namespace.")
@click.pass_obj
def list_cmd(obj: dict[str, object], remote: bool, namespace: str | None) -> None:
    """List cached designs, or designs in a registry namespace with --remote."""
    if namespace is not None and not remote:
        raise click.UsageError("--namespace requires --remote.")
    if remote:
        _list_remote(obj, namespace)
        return

    cache_dir = Path(str(obj["cache_dir"]))
    index = load_index(cache_dir)

    if obj["json"]:
        click.echo(json.dumps([e.model_dump(mode="json") for e in index.entries], indent=2))
        return

    if not index.entries:
        click.echo("No cached designs.")
        return

    rows = [(e.name, e.version, e.platform, e.pulled_at.strftime("%Y-%m-%d")) for e in index.entries]
    _echo_table(("DESIGN", "VERSION", "PLATFORM", "PULLED"), rows)


def _list_remote(obj: dict[str, object], namespace: str | None) -> None:
    try:
        designs = sdk_api.list_remote(namespace=namespace, registry=str(obj["registry"]))
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([d.model_dump(mode="json") for d in designs], indent=2))
        return

    if not designs:
        click.echo("No designs found.")
        return

    rows: list[tuple[str, ...]] = []
    for d in designs:
        platforms = d.platforms[0] if d.platforms else "-"
        if len(d.platforms) > 1:
            platforms += f" +{len(d.platforms) - 1}"
        rows.append((d.name, d.latest_version, platforms, d.updated_at.strftime("%Y-%m-%d")))
    _echo_table(("DESIGN", "VERSION", "PLATFORMS", "PUBLISHED"), rows)
