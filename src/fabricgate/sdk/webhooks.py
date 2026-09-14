"""Webhook management SDK functions."""

from __future__ import annotations

from urllib.parse import urlparse

from fabricgate.client import auth
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import (
    WebhookCreateResult,
    WebhookDeliveryItem,
    WebhookItem,
    WebhookTestResult,
)
from fabricgate.sdk._helpers import ExitKind, SDKError, _registry_error_kind

# ---------------------------------------------------------------------------
# Webhook helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public webhook functions
# ---------------------------------------------------------------------------


def webhook_create(
    *,
    namespace: str,
    url: str,
    events: str,
    design: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> WebhookCreateResult:
    """Create a new webhook.

    Parameters
    ----------
    namespace:
        Namespace to create the webhook in.
    url:
        HTTPS URL to receive webhook deliveries.
    events:
        Comma-separated event types.
    design:
        Optional design filter (only receive events for this design).
    registry:
        Base URL for the registry API.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SDKError("Webhook URL must use HTTPS.", code=ExitKind.INVALID)

    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    event_list = [e.strip() for e in events.split(",") if e.strip()]
    if not event_list:
        raise SDKError("At least one event type is required.", code=ExitKind.INVALID)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.create_webhook(namespace, url, event_list, design)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return WebhookCreateResult(
        id=resp.id,
        url=resp.url,
        events=resp.events,
        design=resp.design,
        secret=resp.secret,
        status=resp.status,
        created_at=resp.created_at,
    )


def webhook_list(
    *,
    namespace: str,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[WebhookItem]:
    """List all webhooks for a namespace."""
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.list_webhooks(namespace)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return [
        WebhookItem(
            id=w.id,
            url=w.url,
            events=w.events,
            design=w.design,
            status=w.status,
            last_delivered_at=w.last_delivered_at,
            created_at=w.created_at,
        )
        for w in resp.webhooks
    ]


def webhook_delete(
    webhook_id: int,
    *,
    namespace: str,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> None:
    """Delete a webhook.

    Parameters
    ----------
    webhook_id:
        Numeric ID of the webhook to delete.
    namespace:
        Owning namespace.
    registry:
        Base URL for the registry API.
    """
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            client.delete_webhook(namespace, webhook_id)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc


def webhook_test(
    webhook_id: int,
    *,
    namespace: str,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> WebhookTestResult:
    """Send a test delivery to a webhook.

    Parameters
    ----------
    webhook_id:
        Numeric ID of the webhook to test.
    namespace:
        Owning namespace.
    registry:
        Base URL for the registry API.
    """
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.test_webhook(namespace, webhook_id)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return WebhookTestResult(
        delivered=resp.delivered,
        status_code=resp.status_code,
        duration_ms=resp.duration_ms,
    )


def webhook_deliveries(
    webhook_id: int,
    *,
    namespace: str,
    limit: int | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[WebhookDeliveryItem]:
    """List delivery logs for a webhook.

    Parameters
    ----------
    webhook_id:
        Numeric ID of the webhook.
    namespace:
        Owning namespace.
    limit:
        Maximum number of deliveries to return.
    registry:
        Base URL for the registry API.
    """
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.list_webhook_deliveries(namespace, webhook_id, limit)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return [
        WebhookDeliveryItem(
            id=d.id,
            event=d.event,
            status_code=d.status_code,
            duration_ms=d.duration_ms,
            delivered_at=d.delivered_at,
            redelivery=d.redelivery,
        )
        for d in resp.deliveries
    ]
