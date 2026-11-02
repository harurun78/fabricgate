"""fabricgate diff command — compare metadata between two design versions."""

from __future__ import annotations

import json
import string

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.cli.formatting import format_size, sanitize
from fabricgate.models.api.responses import VersionDiffField, VersionDiffResponse
from fabricgate.sdk import api as sdk_api


def _format_value(field_name: str, value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if field_name.endswith("size"):
            return format_size(value)
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        if field_name.endswith("sha256") and all(char in string.hexdigits for char in value):
            return value
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _format_field(field: VersionDiffField, width: int) -> str:
    # JSON escapes control characters but not format characters such as bidi overrides.
    before = sanitize(_format_value(field.field, field.base))
    after = sanitize(_format_value(field.field, field.head))
    safe_field = sanitize(field.field)
    return f"  {safe_field.ljust(width)} {before} → {after}"


def _format_platforms(platforms: list[str]) -> str:
    return ", ".join([sanitize(p) for p in platforms]) if platforms else "(none)"


def _render_text(result: VersionDiffResponse, design_ref: str) -> None:
    design_name = design_ref.split(":", 1)[0]
    click.echo(sanitize(f"Diff: {design_name}  {result.base} → {result.head}"))
    click.echo()
    click.echo(f" Platforms added:   {_format_platforms(result.summary.platforms_added)}")
    click.echo(f" Platforms removed: {_format_platforms(result.summary.platforms_removed)}")
    click.echo(f" Platforms changed: {_format_platforms(result.summary.platforms_changed)}")

    if not result.diff:
        click.echo()
        click.echo("No differences found.")
        return

    for entry in result.diff:
        click.echo()
        click.echo(f"{sanitize(entry.platform)}:")
        if entry.fields == "added":
            click.echo(f"  (added in {result.head})")
            continue
        if entry.fields == "removed":
            click.echo(f"  (removed from {result.base})")
            continue

        width = max((len(sanitize(field.field)) for field in entry.fields), default=0)
        for field in entry.fields:
            click.echo(_format_field(field, width))


@click.command(name="diff")
@click.argument("design_ref")
@click.option("--base", "base_ref", required=True, help="Base version or namespace/design:version.")
@click.option("--platform", default=None, help="Compare only one platform (device/runtime).")
@click.pass_obj
def diff_cmd(
    obj: dict[str, object],
    design_ref: str,
    base_ref: str,
    platform: str | None,
) -> None:
    """Show metadata differences between two design versions."""
    reg: str = str(obj["registry"])
    with sdk_errors():
        result = sdk_api.diff(
            design_ref,
            base=base_ref,
            platform=platform,
            registry=reg,
        )

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    _render_text(result, design_ref)
