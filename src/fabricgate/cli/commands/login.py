"""fabricgate login command."""

from __future__ import annotations

import json

import click

from fabricgate.sdk import api as sdk_api


@click.command(name="login")
@click.option("--registry", default=None, help="Registry base URL.")
@click.pass_obj
def login_cmd(obj: dict[str, object], registry: str | None) -> None:
    """Authenticate with the registry."""
    reg: str = registry or str(obj["registry"])
    click.echo(f"Using registry: {reg}\n")

    def _on_user_code(verification_uri: str, user_code: str) -> None:
        click.echo("To authenticate, visit:")
        click.echo(f"  {verification_uri}")
        click.echo(f"  and enter code: {user_code}\n")
        click.echo("Waiting for authorization ...", nl=False)

    try:
        result = sdk_api.login(
            registry=reg,
            on_user_code=_on_user_code,
        )
    except sdk_api.SDKError as exc:
        click.echo(" ✗", err=False)
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(1) from exc

    click.echo(" ✓\n")

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        click.echo(f"Logged in. Token saved to {result.storage}.")
