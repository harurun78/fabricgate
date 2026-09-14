"""Namespace quota SDK function."""

from __future__ import annotations

from fabricgate.client import auth
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.api.responses import QuotaResponse
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _default_namespace_from_scopes,
    _registry_error_kind,
    _validate_namespace_name,
)


def quota(
    *,
    namespace: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> QuotaResponse:
    """Fetch quota usage for a namespace."""
    creds = auth.load_credentials(registry)
    effective_token = token or (creds.token if creds is not None else None)

    ns = namespace
    if ns is None:
        ns = _default_namespace_from_scopes(creds.scopes if creds is not None else [])
        if ns is None:
            raise SDKError(
                "Namespace is required. Specify --namespace or run 'fabricgate login' first.", code=ExitKind.GENERIC
            )

    _validate_namespace_name(ns)

    try:
        with RegistryClient(base_url=registry, token=effective_token) as client:
            return client.get_namespace_quota(ns)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
