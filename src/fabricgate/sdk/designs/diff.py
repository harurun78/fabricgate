"""Version diff SDK function."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.api.responses import VersionDiffResponse
from fabricgate.sdk._helpers import SDKError, _normalize_base_version, _parse_design_ref, _registry_error_kind


def diff(
    design_ref: str,
    *,
    base: str,
    platform: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> VersionDiffResponse:
    """Fetch metadata diff between two versions of a design."""
    namespace, design, version = _parse_design_ref(design_ref)
    base_version = _normalize_base_version(namespace, design, base)

    try:
        with RegistryClient(base_url=registry) as client:
            return client.get_version_diff(namespace, design, version, base_version, platform)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
