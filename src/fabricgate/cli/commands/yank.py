"""fabricgate yank command — version yank (soft-delete)."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="yank")
@click.argument("design_ref")
@click.argument("versions", nargs=-1)
@click.option("--reason", default="", help="Reason for yanking.")
@click.pass_obj
def yank_cmd(
    obj: dict[str, object],
    design_ref: str,
    versions: tuple[str, ...],
    reason: str,
) -> None:
    """Yank (soft-delete) one or more versions."""
    reg: str = str(obj["registry"])
    version_list = list(versions) if versions else None
    try:
        results = sdk_api.yank(
            design_ref,
            version_list,
            reason=reason,
            registry=reg,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    else:
        count = len(results)
        if count == 1:
            click.echo(f"\nYanking {results[0].name}:{results[0].version} ...")
        else:
            click.echo(f"\nYanking {count} versions of {results[0].name} ...")
        for r in results:
            click.echo(f"  \u2713 yanked  {r.name}:{r.version}")
        if reason:
            click.echo(f"  Reason: {reason}")
