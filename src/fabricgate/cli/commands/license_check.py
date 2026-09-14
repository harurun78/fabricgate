"""fabricgate license-check command — tool requirements and compatibility check."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="license-check")
@click.argument("design_ref")
@click.option("--tool", "tools", multiple=True, help="Tool identifier to check (repeatable).")
@click.option("--edition", default=None, help="Edition to check (e.g. standard, enterprise).")
@click.pass_obj
def license_check_cmd(
    obj: dict[str, object],
    design_ref: str,
    tools: tuple[str, ...],
    edition: str | None,
) -> None:
    """Check tool requirements for a design version."""
    reg: str = str(obj["registry"])
    tool_list = list(tools) if tools else None
    try:
        result = sdk_api.license_check(
            design_ref,
            tool=tool_list,
            edition=edition,
            registry=reg,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    click.echo(f"Design:   {result.design}:{result.version}")

    if not result.tool_requirements:
        click.echo("\nNo tool requirements defined.")
        click.echo(f"\nDisclaimer: {result.disclaimer}")
        # GENERIC: no requirements to check (ADR-008). Exit 2 is reserved for
        # PERMISSION; a missing-data signal must not collide with it.
        raise click.exceptions.Exit(1)

    if result.check is not None:
        # Tool/edition check mode
        click.echo(f"\ncheck: {result.check.tool}" + (f" ({result.check.edition})" if result.check.edition else ""))
        symbol = "\u2713" if result.check.meets_requirements else "\u2717"
        for note in result.check.notes:
            click.echo(f"  {symbol}  {note}")
        status = "MEETS REQUIREMENTS" if result.check.meets_requirements else "DOES NOT MEET REQUIREMENTS"
        click.echo(f"\nResult: {status}")
    else:
        # List mode
        click.echo("\nTool Requirements:")
        for req in result.tool_requirements:
            label = "required" if req.required else "optional"
            click.echo(f"  {req.tool} ({label})")
            if req.min_version:
                click.echo(f"    Min version: {req.min_version}")
            if req.edition:
                click.echo(f"    Edition:     {req.edition}")
            if req.note:
                click.echo(f"    Note:        {req.note}")
            click.echo()

    click.echo(f"Disclaimer: {result.disclaimer}")

    if result.check is not None and not result.check.meets_requirements:
        raise click.exceptions.Exit(3)
