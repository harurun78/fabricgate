"""fabricgate login command."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.cli.formatting import sanitize_lines
from fabricgate.sdk import api as sdk_api


@click.command(name="login")
@click.option(
    "--registry",
    default=None,
    help="Registry API base URL, including /api/v1 (default: https://registry.fabricgate.dev/api/v1).",
)
@click.pass_obj
def login_cmd(obj: dict[str, object], registry: str | None) -> None:
    """Authenticate with the registry."""
    reg: str = registry or str(obj["registry"])
    # With --json, stdout carries only the JSON; the guidance goes to stderr, where the user still sees the code.
    to_stderr = bool(obj["json"])
    click.echo(f"Using registry: {reg}\n", err=to_stderr)

    def _on_user_code(verification_uri: str, user_code: str) -> None:
        click.echo("To authenticate, visit:", err=to_stderr)
        click.echo(f"  {verification_uri}", err=to_stderr)
        click.echo(f"  and enter code: {user_code}\n", err=to_stderr)
        click.echo("Waiting for authorization ...", nl=False, err=to_stderr)

    try:
        result = sdk_api.login(
            registry=reg,
            on_user_code=_on_user_code,
        )
    # Not sdk_errors(): the "Waiting for authorization ..." line needs its " ✗" first.
    except sdk_api.SDKError as exc:
        click.echo(" ✗", err=to_stderr)
        click.echo(sanitize_lines(str(exc)), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    click.echo(" ✓\n", err=to_stderr)

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        click.echo(f"Logged in. Token saved to {result.storage}.")
