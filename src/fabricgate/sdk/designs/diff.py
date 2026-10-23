"""Version diff SDK function."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient
from fabricgate.models.api.responses import VersionDiffResponse
from fabricgate.sdk._helpers import _normalize_base_version, _parse_design_ref, _registry_errors


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

    with _registry_errors(), RegistryClient(base_url=registry) as client:
        return client.get_version_diff(namespace, design, version, base_version, platform)
