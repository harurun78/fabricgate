"""Version lifecycle SDK functions: yank, deprecate, undeprecate."""

from __future__ import annotations

from fabricgate.client import auth
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import DeprecateResult, YankResult
from fabricgate.sdk._helpers import ExitKind, SDKError, _parse_design_ref, _registry_error_kind, _validate_semver


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
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    # Parse design ref
    version_list: list[str] = []
    if ":" in design_ref:
        # Single version form: namespace/design:version
        namespace, design, ver = _parse_design_ref(design_ref)
        version_list.append(ver)
    else:
        # Multi version form: namespace/design version1 version2 ...
        parts = design_ref.split("/", 1)
        if len(parts) != 2:
            raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID)
        namespace, design = parts

    if versions:
        version_list.extend(versions)

    for ver in version_list:
        _validate_semver(ver)

    if not version_list:
        raise SDKError("No versions specified.", code=ExitKind.INVALID)

    if len(version_list) > 50:
        raise SDKError("Maximum 50 versions per yank operation.", code=ExitKind.INVALID)

    results: list[YankResult] = []
    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
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
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

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
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    if not message.strip():
        raise SDKError("--message is required unless --undo is used.", code=ExitKind.INVALID)

    version_list: list[str] = []
    if ":" in design_ref:
        namespace, design, ver = _parse_design_ref(design_ref)
        version_list.append(ver)
    else:
        parts = design_ref.split("/", 1)
        if len(parts) != 2:
            raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID)
        namespace, design = parts

    if versions:
        version_list.extend(versions)

    for ver in version_list:
        _validate_semver(ver)

    if not version_list:
        raise SDKError("No versions specified.", code=ExitKind.INVALID)

    if len(version_list) > 50:
        raise SDKError("Maximum 50 versions per deprecate operation.", code=ExitKind.INVALID)

    results: list[DeprecateResult] = []
    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
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
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return results


def undeprecate(
    design_ref: str,
    versions: list[str] | None = None,
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[DeprecateResult]:
    """Clear deprecated state for one or more versions."""
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    version_list: list[str] = []
    if ":" in design_ref:
        namespace, design, ver = _parse_design_ref(design_ref)
        version_list.append(ver)
    else:
        parts = design_ref.split("/", 1)
        if len(parts) != 2:
            raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID)
        namespace, design = parts

    if versions:
        version_list.extend(versions)

    for ver in version_list:
        _validate_semver(ver)

    if not version_list:
        raise SDKError("No versions specified.", code=ExitKind.INVALID)

    if len(version_list) > 50:
        raise SDKError("Maximum 50 versions per deprecate operation.", code=ExitKind.INVALID)

    results: list[DeprecateResult] = []
    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
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
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return results
