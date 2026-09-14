"""Discovery SDK functions: search and per-version info lookups."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import DesignInfo, SearchResult
from fabricgate.sdk._helpers import SDKError, _parse_design_ref, _registry_error_kind


def search(
    query: str | None = None,
    *,
    platform: str | None = None,
    board: str | None = None,
    device_family: str | None = None,
    runtime: str | None = None,
    tag: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> list[SearchResult]:
    """Search for designs in the registry."""
    try:
        with RegistryClient(base_url=registry, token=token) as client:
            response = client.search_designs(
                q=query,
                platform=platform,
                board=board,
                device_family=device_family,
                runtime=runtime,
                tag=tag,
            )
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return [
        SearchResult(
            name=entry.name,
            version=entry.latest_version,
            summary=entry.summary,
            platforms=entry.platforms,
        )
        for entry in response.designs
    ]


def info(
    design_ref: str,
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> DesignInfo:
    """Fetch version-specific metadata for a design reference."""
    namespace, design, version = _parse_design_ref(design_ref)
    try:
        with RegistryClient(base_url=registry, token=token) as client:
            response = client.get_version(namespace, design, version)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return DesignInfo(
        name=response.name,
        version=response.version,
        summary=response.summary,
        license=response.license,
        author=response.author,
        repository=response.repository,
        tags=response.tags,
        platforms=response.platforms,
    )
