"""fabricgate search command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import sdk_errors
from fabricgate.cli.formatting import sanitize
from fabricgate.sdk import api as sdk_api
from fabricgate.sdk.designs.search import SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX


@click.command(name="search")
@click.argument("query", required=False)
@click.option("--platform", default=None, help="Filter by platform.")
@click.option("--board", default=None, help="Filter by board ID.")
@click.option("--device", "device_family", default=None, help="Filter by device family (e.g. xczu7ev).")
# The name used up to v0.4.4, kept (hidden) so existing scripts keep working.
@click.option("--device-family", "device_family_alias", default=None, hidden=True)
@click.option("--runtime", default=None, help="Filter by runtime.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.option(
    "--limit",
    type=int,
    default=SEARCH_LIMIT_DEFAULT,
    show_default=True,
    help=f"Show at most this many designs, most recently updated first (up to {SEARCH_LIMIT_MAX}).",
)
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
    limit: int,
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
            limit=limit,
        )

    if len(results) < results.total:
        # On stderr, so the table and the --json list stay as they are.
        click.echo(
            f"Showing {len(results)} of {results.total} designs. Use --limit (up to {SEARCH_LIMIT_MAX}) "
            "or narrow the search.",
            err=True,
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
        click.echo(sanitize(f"{result.name} {result.version} {platforms} {summary}".rstrip()))
