"""fabricgate verify command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="verify")
@click.argument("directory", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.pass_obj
def verify_cmd(obj: dict[str, object], directory: Path) -> None:
    """Verify artifact digests in a pulled design directory."""
    try:
        result = sdk_api.verify(directory)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    click.echo(f"Verifying {result.design_ref} ({result.platform}) ...")
    failed = False
    for artifact in result.artifacts:
        status = "OK" if artifact.verified else "FAIL"
        click.echo(f"  {artifact.file} sha256:{artifact.sha256} {status}")
        failed = failed or not artifact.verified

    if failed:
        raise click.exceptions.Exit(3)
    click.echo("All artifacts verified.")
