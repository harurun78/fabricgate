"""fabricgate deprecate command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="deprecate")
@click.option("--undo", is_flag=True, help="Clear deprecated state instead of setting it.")
@click.option("--message", default="", help="Deprecation message.")
@click.option("--successor", default=None, help="Suggested successor design ref.")
@click.argument("design_ref")
@click.argument("versions", nargs=-1)
@click.pass_obj
def deprecate_cmd(
    obj: dict[str, object],
    undo: bool,
    message: str,
    successor: str | None,
    design_ref: str,
    versions: tuple[str, ...],
) -> None:
    """Deprecate or undeprecate one or more versions."""
    reg: str = str(obj["registry"])
    version_list = list(versions) if versions else None

    if undo and message:
        raise click.UsageError("--message cannot be used with --undo.")
    if undo and successor:
        raise click.UsageError("--successor cannot be used with --undo.")
    if not undo and not message.strip():
        raise click.UsageError("--message is required unless --undo is used.")

    try:
        if undo:
            results = sdk_api.undeprecate(
                design_ref,
                version_list,
                registry=reg,
            )
        else:
            results = sdk_api.deprecate(
                design_ref,
                version_list,
                message=message,
                successor=successor,
                registry=reg,
            )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        return

    count = len(results)
    action = "Undeprecating" if undo else "Deprecating"
    if count == 1:
        click.echo(f"\n{action} {results[0].name}:{results[0].version} ...")
    else:
        click.echo(f"\n{action} {count} versions of {results[0].name} ...")

    marker = "undeprecated" if undo else "deprecated"
    for result in results:
        click.echo(f"  ✓ {marker}  {result.name}:{result.version}")

    if not undo:
        if message:
            click.echo(f"  Message: {message}")
        if successor:
            click.echo(f"  Successor: {successor}")
