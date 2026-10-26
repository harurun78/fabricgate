"""fabricgate search command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.sdk import api as sdk_api


@click.command(name="search")
@click.argument("query", required=False)
@click.option("--platform", default=None, help="Filter by platform.")
@click.option("--board", default=None, help="Filter by board ID.")
@click.option("--device", "device_family", default=None, help="Filter by device family (e.g. xczu7ev).")
# The name used up to v0.4.4, kept (hidden) so existing scripts keep working.
@click.option("--device-family", "device_family_alias", default=None, hidden=True)
@click.option("--runtime", default=None, help="Filter by runtime.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.pass_obj
def search_cmd(
    obj: dict[str, object],
    query: str | None,
    platform: str | None,
    board: str | None,
    device_family: str | None,
    device_family_alias: str | None,
    runtime: str | None,
    tag: str | None,
) -> None:
    """Search for designs in the registry."""
    with sdk_errors():
        results = sdk_api.search(
            query,
            platform=platform,
            board=board,
            device_family=device_family or device_family_alias,
            runtime=runtime,
            tag=tag,
            registry=str(obj["registry"]),
        )

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
