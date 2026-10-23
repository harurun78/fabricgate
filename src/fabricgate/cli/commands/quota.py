"""fabricgate quota command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.sdk import api as sdk_api
from fabricgate.sdk._helpers import _quota_warning_message

_BAR_WIDTH = 32


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    num = float(value)
    unit = units[0]
    for unit in units:
        if num < 1024.0 or unit == units[-1]:
            break
        num /= 1024.0
    if unit == "B":
        return f"{int(num)} {unit}"
    return f"{num:.1f} {unit}"


def _render_quota_bar(percent: float) -> str:
    clamped = max(0.0, min(100.0, percent))
    filled = round(clamped / 100.0 * _BAR_WIDTH)
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


@click.command(name="quota")
@click.option("--namespace", default=None, help="Target namespace. Defaults to your authenticated namespace.")
@click.pass_obj
def quota_cmd(obj: dict[str, object], namespace: str | None) -> None:
    """Show namespace quota usage."""
    with sdk_errors():
        result = sdk_api.quota(
            namespace=namespace,
            registry=str(obj["registry"]),
        )

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    used_percent = result.storage.used_percent
    message = _quota_warning_message(result)
    warning = f"  ⚠ {message}" if message else ""

    click.echo(f"Namespace: {result.namespace}")
    click.echo("")
    click.echo(
        "  Storage"
        f"    {_format_bytes(result.storage.used_bytes):>7} / {_format_bytes(result.storage.limit_bytes):>7}"
        f"   [{_render_quota_bar(used_percent)}]"
        f"  {round(used_percent):>3}%{warning}"
    )
    click.echo(f"  Designs    {result.designs.used:>5} / {result.designs.limit}")
    click.echo(f"  Versions / design limit: {result.versions_per_design.limit}")
    click.echo(f"  Max file size: {_format_bytes(result.file_size_limit_bytes)}")
