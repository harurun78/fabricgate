"""fabricgate stats command."""

from __future__ import annotations

import json
from typing import Literal, cast

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.models.cli import NamespaceStatsInfo
from fabricgate.sdk import api as sdk_api


def _render_ascii_bar(downloads: int, max_downloads: int, width: int = 40) -> str:
    if downloads <= 0 or max_downloads <= 0:
        return ""
    bar_len = max(1, int(downloads * width / max_downloads))
    return "#" * bar_len


@click.command(name="stats")
@click.argument("design_ref", required=False)
@click.option("--namespace", "namespace", default=None, help="Show namespace statistics.")
@click.option(
    "--period",
    default="daily",
    type=click.Choice(["daily", "weekly", "monthly"], case_sensitive=False),
    show_default=True,
    help="Aggregation period.",
)
@click.option("--from", "from_date", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--to", "to_date", default=None, help="End date (YYYY-MM-DD).")
@click.option("--version", default=None, help="Filter by design version.")
@click.pass_obj
def stats_cmd(
    obj: dict[str, object],
    design_ref: str | None,
    namespace: str | None,
    period: str,
    from_date: str | None,
    to_date: str | None,
    version: str | None,
) -> None:
    """Show download statistics for a design or namespace."""
    if bool(design_ref) == bool(namespace):
        raise click.UsageError("Specify exactly one target: <design-ref> or --namespace <ns>.")

    try:
        selected_period = cast(Literal["daily", "weekly", "monthly"], period)
        result = sdk_api.stats(
            design_ref=design_ref,
            namespace=namespace,
            period=selected_period,
            from_date=from_date,
            to_date=to_date,
            version=version,
            registry=str(obj["registry"]),
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    if isinstance(result, NamespaceStatsInfo):
        click.echo(f"Namespace: {result.namespace}  (total: {result.total_downloads:,} downloads)")
        click.echo("")
        click.echo("Top designs:")
        if not result.top_designs:
            click.echo("  (no data)")
        else:
            for idx, top_design in enumerate(result.top_designs, start=1):
                click.echo(f"  {idx}. {top_design.name:<24} {top_design.total_downloads:,}")
        click.echo("")
        click.echo(f"  Last 7d: {result.last_7d:,}    Last 30d: {result.last_30d:,}")
        return

    header_name = result.name if result.version is None else f"{result.name}:{result.version}"
    click.echo(f"{header_name}  (total: {result.total_downloads:,} downloads)")
    click.echo("")
    click.echo(f"{result.period.capitalize()} downloads")

    max_downloads = max((item.downloads for item in result.series), default=0)
    if not result.series:
        click.echo("  (no data)")
    else:
        for point in result.series:
            bar = _render_ascii_bar(point.downloads, max_downloads)
            click.echo(f"  {point.date}  {bar:<40}  {point.downloads}")

    click.echo("")
    click.echo(f"  Last 7d: {result.last_7d:,}    Last 30d: {result.last_30d:,}")
