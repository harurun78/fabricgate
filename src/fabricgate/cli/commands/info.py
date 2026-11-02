"""fabricgate info command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.cli.formatting import sanitize
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

    click.echo(f"Name: {sanitize(result.name)}")
    click.echo(f"Version: {sanitize(result.version)}")
    if result.summary:
        click.echo(f"Summary: {sanitize(result.summary)}")
    if result.license:
        click.echo(f"License: {sanitize(result.license)}")
    if result.author:
        click.echo(f"Author: {sanitize(result.author)}")
    if result.repository:
        click.echo(f"Repository: {sanitize(result.repository)}")
    if result.tags:
        click.echo(f"Tags: {', '.join(sanitize(t) for t in result.tags)}")
    click.echo("Platforms:")
    for platform in result.platforms:
        click.echo(f"  {sanitize(platform.platform)}")
