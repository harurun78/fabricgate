"""fabricgate webhook command — webhook management."""

from __future__ import annotations

import json

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


# Hidden until the registry implements the webhooks endpoints: the hosted
# service answers 404 for every call these subcommands make, so the group is
# kept out of `--help` rather than advertising a surface that cannot work.
# See https://github.com/harurun78/fabricgate/issues/6
@click.group(name="webhook", hidden=True)
@click.pass_obj
def webhook_group(obj: dict[str, object]) -> None:
    """Manage webhooks for namespace event notifications."""


@webhook_group.command(name="create")
@click.option("--namespace", required=True, help="Namespace to create the webhook in.")
@click.option("--url", required=True, help="HTTPS URL to receive deliveries.")
@click.option("--events", required=True, help="Comma-separated event types.")
@click.option("--design", default=None, help="Filter events to a specific design.")
@click.pass_obj
def webhook_create_cmd(
    obj: dict[str, object],
    namespace: str,
    url: str,
    events: str,
    design: str | None,
) -> None:
    """Create a new webhook."""
    reg: str = str(obj["registry"])
    try:
        result = sdk_api.webhook_create(
            namespace=namespace,
            url=url,
            events=events,
            design=design,
            registry=reg,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        click.echo(f"  ID:     {result.id}")
        click.echo(f"  URL:    {result.url}")
        click.echo(f"  Events: {', '.join(result.events)}")
        if result.design:
            click.echo(f"  Design: {result.design}")
        click.echo(f"  Status: {result.status}")
        click.echo(f"\n  Secret: {result.secret}\n")
        click.echo(
            "  \u26a0  This secret is shown only once. Store it in a safe place.",
            err=True,
        )


@webhook_group.command(name="list")
@click.option("--namespace", required=True, help="Namespace to list webhooks for.")
@click.pass_obj
def webhook_list_cmd(obj: dict[str, object], namespace: str) -> None:
    """List all webhooks for a namespace."""
    reg: str = str(obj["registry"])
    try:
        webhooks = sdk_api.webhook_list(namespace=namespace, registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([w.model_dump(mode="json") for w in webhooks], indent=2))
    else:
        if not webhooks:
            click.echo("No webhooks found.")
            return
        click.echo(f"{'ID':<5} {'URL':<40} {'EVENTS':<30} {'STATUS':<10} {'LAST DELIVERED'}")
        for w in webhooks:
            last = str(w.last_delivered_at) if w.last_delivered_at else "(never)"
            click.echo(f"{w.id:<5} {w.url:<40} {', '.join(w.events):<30} {w.status:<10} {last}")


@webhook_group.command(name="delete")
@click.argument("webhook_id", type=int)
@click.option("--namespace", required=True, help="Owning namespace.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def webhook_delete_cmd(
    obj: dict[str, object],
    webhook_id: int,
    namespace: str,
    force: bool,
) -> None:
    """Delete a webhook."""
    if not force and not obj["json"]:
        if not click.confirm(f"Delete webhook (id: {webhook_id})?", default=False):
            raise click.exceptions.Exit(0)

    reg: str = str(obj["registry"])
    try:
        sdk_api.webhook_delete(webhook_id, namespace=namespace, registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps({"deleted": True, "id": webhook_id}))
    else:
        click.echo("Deleted.")


@webhook_group.command(name="test")
@click.argument("webhook_id", type=int)
@click.option("--namespace", required=True, help="Owning namespace.")
@click.pass_obj
def webhook_test_cmd(
    obj: dict[str, object],
    webhook_id: int,
    namespace: str,
) -> None:
    """Send a test delivery to a webhook."""
    reg: str = str(obj["registry"])
    try:
        result = sdk_api.webhook_test(webhook_id, namespace=namespace, registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        mark = "\u2713" if result.delivered else "\u2717"
        click.echo(f"  {mark}  Status: {result.status_code}  Duration: {result.duration_ms}ms")


@webhook_group.command(name="deliveries")
@click.argument("webhook_id", type=int)
@click.option("--namespace", required=True, help="Owning namespace.")
@click.option("--limit", type=int, default=None, help="Maximum number of deliveries.")
@click.pass_obj
def webhook_deliveries_cmd(
    obj: dict[str, object],
    webhook_id: int,
    namespace: str,
    limit: int | None,
) -> None:
    """View delivery logs for a webhook."""
    reg: str = str(obj["registry"])
    try:
        deliveries = sdk_api.webhook_deliveries(webhook_id, namespace=namespace, limit=limit, registry=reg)
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps([d.model_dump(mode="json") for d in deliveries], indent=2))
    else:
        if not deliveries:
            click.echo("No deliveries found.")
            return
        click.echo(f"{'ID':<20} {'EVENT':<30} {'STATUS':<8} {'DURATION':<10} {'DELIVERED AT'}")
        for d in deliveries:
            click.echo(f"{d.id:<20} {d.event:<30} {d.status_code:<8} {d.duration_ms:<10} {d.delivered_at}")
