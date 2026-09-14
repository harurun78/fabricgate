"""Watch SDK function: detect newer versions of a design or shell."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import WatchResult
from fabricgate.sdk._helpers import ExitKind, SDKError, _parse_design_ref_optional_version, _registry_error_kind


def _parse_semver_tuple(version: str) -> tuple[int, int, int]:
    """Return (major, minor, patch) for semver comparison, ignoring pre-release suffixes."""
    # Strip pre-release/build metadata (e.g. "1.0.0-beta.1" → "1.0.0")
    core = version.split("-")[0].split("+")[0]
    parts = core.split(".")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError) as exc:
        raise SDKError(f"Invalid semver string: {version!r}", code=ExitKind.INVALID) from exc


def watch(
    design_ref: str | None = None,
    *,
    shell: str | None = None,
    since_version: str | None = None,
    platform: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> WatchResult:
    """Check whether a newer version of a design (or shell) is available.

    Exactly one of *design_ref* or *shell* must be provided.

    Returns a :class:`WatchResult`.  The caller is responsible for mapping
    ``new_version_found`` to the appropriate process exit code (0 = found,
    1 = not found).
    """
    if not design_ref and not shell:
        raise SDKError("Either <design-ref> or --shell must be provided.", code=ExitKind.INVALID)
    if design_ref and shell:
        raise SDKError("<design-ref> and --shell are mutually exclusive.", code=ExitKind.INVALID)

    ref = (shell or design_ref) or ""
    namespace, design, _ = _parse_design_ref_optional_version(ref)

    try:
        with RegistryClient(base_url=registry, token=token) as client:
            response = client.get_design(namespace, design)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
    except OSError as exc:
        raise SDKError(f"Network error: {exc}", code=ExitKind.INFRA) from exc

    full_name = f"{namespace}/{design}"

    # Collect non-yanked versions, newest first
    active_versions = [v for v in response.versions if not v.yanked]
    latest_version = active_versions[0].version if active_versions else None

    if not since_version:
        # No version filter — just confirm the design exists and show latest
        return WatchResult(
            design_name=full_name,
            new_version_found=False,
            latest_version=latest_version,
            new_versions=[],
            platforms=[],
        )

    since_tuple = _parse_semver_tuple(since_version)

    matching: list[tuple[tuple[int, int, int], str, list[str]]] = []
    for ver_summary in active_versions:
        ver_tuple = _parse_semver_tuple(ver_summary.version)
        if ver_tuple <= since_tuple:
            continue
        if platform and platform not in ver_summary.platforms:
            continue
        matching.append((ver_tuple, ver_summary.version, list(ver_summary.platforms)))

    if not matching:
        return WatchResult(
            design_name=full_name,
            new_version_found=False,
            latest_version=latest_version,
            new_versions=[],
            platforms=[],
        )

    # Sort newest first
    matching.sort(key=lambda x: x[0], reverse=True)
    newest_platforms = matching[0][2]
    new_version_strs = [m[1] for m in matching]

    return WatchResult(
        design_name=full_name,
        new_version_found=True,
        latest_version=new_version_strs[0],
        new_versions=new_version_strs,
        platforms=newest_platforms,
    )
