"""fabricgate token command — API key management."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.group(name="token")
@click.pass_obj
def token_group(obj: dict[str, object]) -> None:
    """Manage API keys for CI/CD and automation."""


@token_group.command(name="create")
@click.option("--name", required=True, help="Human-readable name for the API key.")
@click.option("--scopes", default=None, help="Comma-separated scopes (default: public:read).")
@click.option("--expires", default=None, help="Expiry: ISO 8601 or relative (e.g. 90d).")
@click.pass_obj
def token_create_cmd(
    obj: dict[str, object],
    name: str,
    scopes: str | None,
    expires: str | None,
) -> None:
    """Create a new API key."""
    reg: str = str(obj["registry"])
    try:
        result = sdk_api.token_create(
            name=name,
            scopes=scopes,
            expires=expires,
            registry=reg,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        expires_str = str(result.expires_at) if result.expires_at else "(never)"
        click.echo(f"  Name:    {result.name}")
        click.echo(f"  Scopes:  {', '.join(result.scopes)}")
        click.echo(f"  Expires: {expires_str}")
        click.echo(f"\n  Token: {result.key}\n")
        click.echo(
            "  \u26a0  This token is shown only once. Store it in a safe place.",
            err=True,
        )


@token_group.command(name="list")
@click.pass_obj
def token_list_cmd(obj: dict[str, object]) -> None:
    """List all API keys."""
    reg: str = str(obj["registry"])
    try:
        keys = sdk_api.token_list(registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([k.model_dump(mode="json") for k in keys], indent=2))
    else:
        if not keys:
            click.echo("No API keys found.")
            return
        # Table header
        click.echo(f"{'ID':<5} {'NAME':<20} {'SCOPES':<30} {'EXPIRES':<16} {'LAST USED'}")
        for k in keys:
            expires = str(k.expires_at.date()) if k.expires_at else "(never)"
            last_used = str(k.last_used_at.date()) if k.last_used_at else "(never)"
            click.echo(f"{k.id:<5} {k.name:<20} {', '.join(k.scopes):<30} {expires:<16} {last_used}")


@token_group.command(name="revoke")
@click.argument("token_id", type=int)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def token_revoke_cmd(
    obj: dict[str, object],
    token_id: int,
    force: bool,
) -> None:
    """Revoke an API key."""
    if not force and not obj["json"]:
        if not click.confirm(f"Revoke API key (id: {token_id})?", default=False):
            raise click.exceptions.Exit(0)

    reg: str = str(obj["registry"])
    try:
        sdk_api.token_revoke(token_id, registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps({"revoked": True, "id": token_id}))
    else:
        click.echo("Revoked.")
