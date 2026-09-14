"""fabricgate search command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="search")
@click.argument("query", required=False)
@click.option("--platform", default=None, help="Filter by platform.")
@click.option("--board", default=None, help="Filter by board ID.")
@click.option("--device-family", default=None, help="Filter by device family.")
@click.option("--runtime", default=None, help="Filter by runtime.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.pass_obj
def search_cmd(
    obj: dict[str, object],
    query: str | None,
    platform: str | None,
    board: str | None,
    device_family: str | None,
    runtime: str | None,
    tag: str | None,
) -> None:
    """Search for designs in the registry."""
    try:
        results = sdk_api.search(
            query,
            platform=platform,
            board=board,
            device_family=device_family,
            runtime=runtime,
            tag=tag,
            registry=str(obj["registry"]),
        )
    except sdk_api.SDKError as exc:
        exit_code = exit_code_for(exc)
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code) from exc

    if obj["json"]:
        click.echo(json.dumps([result.model_dump(mode="json") for result in results], indent=2))
        return

    if not results:
        click.echo("No designs found.")
        return

    click.echo("NAME VERSION PLATFORMS SUMMARY")
    for result in results:
        platforms = ",".join(result.platforms)
        summary = result.summary or ""
        click.echo(f"{result.name} {result.version} {platforms} {summary}".rstrip())
