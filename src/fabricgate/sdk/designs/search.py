"""Discovery SDK functions: search and per-version info lookups."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient
from fabricgate.models.api.responses import DesignSummary
from fabricgate.models.cli import DesignInfo, SearchResult, SearchResults
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _default_namespace_from_scopes,
    _parse_design_ref,
    _registry_errors,
    _stored_credentials,
    _validate_namespace_name,
)

_LIST_PAGE_SIZE = 100  # API maximum for per_page
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 1000  # at most 10 requests of the API maximum page


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
    limit: int = SEARCH_LIMIT_DEFAULT,
) -> SearchResults:
    """Search for designs in the registry, most recently updated first.

    Returns at most *limit* designs (1 to 1000), fetching more than one page when
    *limit* is over the API's page size; ``total`` on the result says how many match.
    """
    if not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise SDKError(f"--limit must be between 1 and {SEARCH_LIMIT_MAX}.", code=ExitKind.INVALID)
    per_page = min(limit, _LIST_PAGE_SIZE)  # the same size on every page, so pages do not overlap
    designs: list[DesignSummary] = []
    with _registry_errors(), RegistryClient(base_url=registry, token=token) as client:
        page = 1
        while True:
            response = client.search_designs(
                q=query,
                platform=platform,
                board=board,
                device_family=device_family,
                runtime=runtime,
                tag=tag,
                page=page,
                per_page=per_page,
            )
            designs.extend(response.designs)
            if len(designs) >= min(limit, response.total) or len(response.designs) < per_page:
                break
            page += 1

    results = [
        SearchResult(
            name=entry.name,
            version=entry.latest_version,
            summary=entry.summary,
            platforms=entry.platforms,
        )
        for entry in designs[:limit]
    ]
    return SearchResults(results, total=response.total)


def list_remote(
    *,
    namespace: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> list[DesignSummary]:
    """List every design published in a namespace (``fabricgate list --remote``).

    Without *namespace* the caller's own namespace is derived from the stored
    credentials; if none are stored the failure kind is ``PERMISSION``.
    """
    # An explicit token needs no stored credentials, so a damaged store does not get in its way.
    creds = None if token else _stored_credentials(registry)
    effective_token = token or (creds.token if creds is not None else None)

    ns = namespace
    if ns is None:
        if creds is None:
            raise SDKError(
                "Authentication required. Run 'fabricgate login' or specify --namespace.",
                code=ExitKind.PERMISSION,
            )
        ns = _default_namespace_from_scopes(creds.scopes)
        if ns is None:
            raise SDKError("Namespace is required. Specify --namespace.", code=ExitKind.GENERIC)

    _validate_namespace_name(ns)

    designs: list[DesignSummary] = []
    with _registry_errors(), RegistryClient(base_url=registry, token=effective_token) as client:
        page = 1
        while True:
            response = client.search_designs(namespace=ns, page=page, per_page=_LIST_PAGE_SIZE)
            designs.extend(response.designs)
            if not response.designs or len(designs) >= response.total:
                break
            page += 1
    return designs


def info(
    design_ref: str,
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> DesignInfo:
    """Fetch version-specific metadata for a design reference."""
    namespace, design, version = _parse_design_ref(design_ref)
    with _registry_errors(), RegistryClient(base_url=registry, token=token) as client:
        response = client.get_version(namespace, design, version)

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
