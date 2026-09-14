"""fabricgate quota command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api

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
    try:
        result = sdk_api.quota(
            namespace=namespace,
            registry=str(obj["registry"]),
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    used_percent = result.storage.used_percent
    designs_percent = (result.designs.used / result.designs.limit * 100) if result.designs.limit > 0 else 0.0
    warning = "  ⚠ 上限に近づいています" if used_percent >= 80 or designs_percent >= 80 else ""

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
