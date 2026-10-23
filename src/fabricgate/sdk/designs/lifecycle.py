"""Version lifecycle SDK functions: yank, deprecate, undeprecate."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient
from fabricgate.models.cli import DeprecateResult, YankResult
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _parse_design_ref,
    _parse_design_ref_optional_version,
    _registry_errors,
    _require_token,
    _validate_semver,
)


def _parse_versions(design_ref: str, versions: list[str] | None, operation: str) -> tuple[str, str, list[str]]:
    """Split ``ns/design[:version]`` plus *versions* into (namespace, design, versions), validated."""
    version_list: list[str] = []
    if ":" in design_ref:
        # Single version form: namespace/design:version
        namespace, design, ver = _parse_design_ref(design_ref)
        version_list.append(ver)
    else:
        # Multi version form: namespace/design version1 version2 ...
        namespace, design, _ = _parse_design_ref_optional_version(design_ref)

    if versions:
        version_list.extend(versions)

    for ver in version_list:
        _validate_semver(ver)

    if not version_list:
        raise SDKError("No versions specified.", code=ExitKind.INVALID)

    if len(version_list) > 50:
        raise SDKError(f"Maximum 50 versions per {operation} operation.", code=ExitKind.INVALID)

    return namespace, design, version_list


def yank(
    design_ref: str,
    versions: list[str] | None = None,
    *,
    reason: str = "",
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[YankResult]:
    """Yank one or more versions of a design.

    Parameters
    ----------
    design_ref:
        ``namespace/design:version`` (single) or ``namespace/design`` (multi).
    versions:
        Additional versions to yank (for multi-version form).
    reason:
        Reason for yanking.
    registry:
        Base URL for the registry API.

    Returns
    -------
    list[YankResult]
        Results for each yanked version.
    """
    token = _require_token(registry)

    namespace, design, version_list = _parse_versions(design_ref, versions, "yank")

    results: list[YankResult] = []
    with _registry_errors(), RegistryClient(base_url=registry, token=token) as client:
        for ver in version_list:
            resp = client.yank_version(namespace, design, ver, reason)
            results.append(
                YankResult(
                    name=resp.name,
                    version=resp.version,
                    yanked=resp.yanked,
                    yanked_reason=resp.yanked_reason,
                )
            )

    return results


def deprecate(
    design_ref: str,
    versions: list[str] | None = None,
    *,
    message: str,
    successor: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[DeprecateResult]:
    """Set one or more versions to deprecated state."""
    token = _require_token(registry)

    if not message.strip():
        raise SDKError("--message is required unless --undo is used.", code=ExitKind.INVALID)

    namespace, design, version_list = _parse_versions(design_ref, versions, "deprecate")

    results: list[DeprecateResult] = []
    with _registry_errors(), RegistryClient(base_url=registry, token=token) as client:
        for ver in version_list:
            resp = client.deprecate_version(
                namespace,
                design,
                ver,
                message=message,
                successor=successor,
            )
            results.append(
                DeprecateResult(
                    name=resp.name,
                    version=resp.version,
                    deprecated=resp.deprecated,
                    deprecation_message=resp.deprecation_message,
                    successor=resp.successor,
                )
            )

    return results


def undeprecate(
    design_ref: str,
    versions: list[str] | None = None,
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[DeprecateResult]:
    """Clear deprecated state for one or more versions."""
    token = _require_token(registry)

    namespace, design, version_list = _parse_versions(design_ref, versions, "deprecate")

    results: list[DeprecateResult] = []
    with _registry_errors(), RegistryClient(base_url=registry, token=token) as client:
        for ver in version_list:
            resp = client.undeprecate_version(namespace, design, ver)
            results.append(
                DeprecateResult(
                    name=resp.name,
                    version=resp.version,
                    deprecated=resp.deprecated,
                    deprecation_message=resp.deprecation_message,
                    successor=resp.successor,
                )
            )

    return results
