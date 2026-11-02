"""fabricgate info command."""

from __future__ import annotations

import json

import click
import yaml

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.cli.formatting import format_size, sanitize
from fabricgate.models.board_db import BoardDb
from fabricgate.sdk import api as sdk_api


def _board_names() -> dict[str, str]:
    """Board ID → display name from the local Board DB; empty if it cannot be read (the name is only a label)."""
    try:
        return {b.board_id: b.display_name for b in BoardDb.load().boards}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


@click.command(name="info")
@click.argument("design_ref")
@click.pass_obj
def info_cmd(obj: dict[str, object], design_ref: str) -> None:
    """Show detailed metadata for a design reference."""
    with sdk_errors():
        result = sdk_api.info(design_ref, registry=str(obj["registry"]))

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    # Values start in one column, after the longest label ("Repository: "), as in CLI spec §3.5.
    fields = [
        ("Name", result.name),
        ("Version", result.version),
        ("Summary", result.summary),
        ("License", result.license),
        ("Author", result.author),
        ("Repository", result.repository),
        ("Tags", ", ".join(result.tags)),
    ]
    for label, value in fields:
        if value:
            click.echo(f"{label + ':':<12}{sanitize(value)}")
    click.echo("\nPlatforms:")
    board_names = _board_names()
    for i, platform in enumerate(result.platforms):
        if i:
            click.echo()
        click.echo(f"  {sanitize(platform.platform)}")
        board_id = platform.platform.split("/", 1)[0]
        board = f"{board_id}  ({board_names[board_id]})" if board_id in board_names else board_id
        click.echo(f"    Board:       {sanitize(board)}")
        if platform.speed_grade:
            grade = f"min {platform.speed_grade.min}"
            if platform.speed_grade.tested:
                grade += f", tested [{', '.join(platform.speed_grade.tested)}]"
            click.echo(f"    Speed grade: {sanitize(grade)}")
        if platform.size is not None:
            click.echo(f"    Size:        {format_size(platform.size)}")
        # Only registry responses (ApiPlatformEntry) carry the artifact list.
        artifacts = getattr(platform, "artifacts", [])
        if artifacts:
            click.echo(f"    Artifacts:   {', '.join(sanitize(a.filename) for a in artifacts)}")
