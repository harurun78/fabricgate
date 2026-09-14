"""fabricgate watch command — check for newer versions of a design or shell."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="watch")
@click.argument("design_ref", required=False)
@click.option("--shell", "shell_ref", default=None, help="Monitor a shell design instead.")
@click.option("--since-version", default=None, metavar="X.Y.Z", help="Report versions newer than this.")
@click.option("--platform", default=None, help="Filter by platform (board_id/runtime).")
@click.pass_obj
def watch_cmd(
    obj: dict[str, object],
    design_ref: str | None,
    shell_ref: str | None,
    since_version: str | None,
    platform: str | None,
) -> None:
    """Check whether a newer version of a design or shell is available.

    Exits 0 if a new version was found, 1 if no new version exists or the
    design was not found, 2 on permission errors (access-controlled resource),
    3 on invalid input, and 4 on network errors (ADR-008 exit-code standard).
    """
    try:
        result = sdk_api.watch(
            design_ref=design_ref,
            shell=shell_ref,
            since_version=since_version,
            platform=platform,
            registry=str(obj["registry"]),
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        if not result.new_version_found:
            raise click.exceptions.Exit(1)
        return

    if result.new_version_found:
        newest = result.latest_version
        platforms_str = ", ".join(result.platforms) if result.platforms else "(unknown)"
        click.echo(f"New version found: {result.design_name}:{newest}  (platforms: {platforms_str})")
    else:
        latest_info = f" (latest: {result.latest_version})" if result.latest_version else ""
        ref = result.design_name
        click.echo(f"No new version found for {ref}{latest_info}")
        raise click.exceptions.Exit(1)
