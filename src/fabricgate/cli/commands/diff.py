"""fabricgate diff command — compare metadata between two design versions."""

from __future__ import annotations

import json
import string
from collections.abc import Iterable

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.models.api.responses import VersionDiffField, VersionDiffResponse
from fabricgate.sdk import api as sdk_api


def _sanitize_label(value: str) -> str:
    return "".join(ch if ch.isprintable() and ch not in "\r\n\t" else "?" for ch in value)


def _sanitize_labels(values: Iterable[str]) -> list[str]:
    return [_sanitize_label(v) for v in values]


def _format_size(value: int) -> str:
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            if size.is_integer():
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(value)} B"  # pragma: no cover


def _format_value(field_name: str, value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if field_name.endswith("size"):
            return _format_size(value)
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        if field_name.endswith("sha256") and all(char in string.hexdigits for char in value):
            return value
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _format_field(field: VersionDiffField, width: int) -> str:
    before = _format_value(field.field, field.base)
    after = _format_value(field.field, field.head)
    safe_field = _sanitize_label(field.field)
    return f"  {safe_field.ljust(width)} {before} → {after}"


def _format_platforms(platforms: list[str]) -> str:
    return ", ".join(_sanitize_labels(platforms)) if platforms else "(none)"


def _render_text(result: VersionDiffResponse, design_ref: str) -> None:
    design_name = design_ref.split(":", 1)[0]
    click.echo(f"Diff: {design_name}  {result.base} → {result.head}")
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
        click.echo(f"{_sanitize_label(entry.platform)}:")
        if entry.fields == "added":
            click.echo(f"  (added in {result.head})")
            continue
        if entry.fields == "removed":
            click.echo(f"  (removed from {result.base})")
            continue

        width = max(len(_sanitize_label(field.field)) for field in entry.fields)
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
    try:
        result = sdk_api.diff(
            design_ref,
            base=base_ref,
            platform=platform,
            registry=reg,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    _render_text(result, design_ref)
