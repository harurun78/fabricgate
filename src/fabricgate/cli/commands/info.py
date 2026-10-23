"""fabricgate info command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.sdk import api as sdk_api


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

    click.echo(f"Name: {result.name}")
    click.echo(f"Version: {result.version}")
    if result.summary:
        click.echo(f"Summary: {result.summary}")
    if result.license:
        click.echo(f"License: {result.license}")
    if result.author:
        click.echo(f"Author: {result.author}")
    if result.repository:
        click.echo(f"Repository: {result.repository}")
    if result.tags:
        click.echo(f"Tags: {', '.join(result.tags)}")
    click.echo("Platforms:")
    for platform in result.platforms:
        click.echo(f"  {platform.platform}")
