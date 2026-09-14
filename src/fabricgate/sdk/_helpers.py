"""Shared helpers and error types for the fabricgate SDK."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import TypeAdapter, ValidationError

from fabricgate.client.errors import FailureKind as FailureKind
from fabricgate.client.registry_client import RegistryError
from fabricgate.models.api.responses import QuotaResponse
from fabricgate.models.cli import StatsSeriesItem
from fabricgate.models.common import DesignName, NamespaceName, SemVer
from fabricgate.models.platform_manifest import PlatformManifest

# Backward-compatible alias: ExitKind is public SDK API (fg.SDKError.code).
# New code should use FailureKind. Targeted for removal at 1.0.
ExitKind = FailureKind

_NAMESPACE_NAME_ADAPTER: TypeAdapter[str] = TypeAdapter(NamespaceName)
_DESIGN_NAME_ADAPTER: TypeAdapter[str] = TypeAdapter(DesignName)
_SEMVER_ADAPTER: TypeAdapter[str] = TypeAdapter(SemVer)


@runtime_checkable
class _ArtifactRef(Protocol):
    """Protocol for artifact entries returned by ``_extract_artifact_refs``."""

    file: str
    sha256: str


class SDKError(Exception):
    """Raised when an SDK operation fails.

    Carries a semantic :class:`FailureKind` (``code``, aliased as ``ExitKind``
    for backward compatibility) — not a process exit code. The CLI maps
    ``code`` to an exit status; library callers inspect ``code``.
    """

    def __init__(self, message: str, code: ExitKind = ExitKind.GENERIC) -> None:
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Design ref parsing and validation
# ---------------------------------------------------------------------------


def _parse_design_ref(design_ref: str) -> tuple[str, str, str]:
    try:
        name, version = design_ref.split(":", 1)
        namespace, design = name.split("/", 1)
    except ValueError as exc:
        raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID) from exc
    return namespace, design, version


def _parse_design_ref_optional_version(design_ref: str) -> tuple[str, str, str | None]:
    version: str | None = None
    name = design_ref
    if ":" in design_ref:
        name, version = design_ref.split(":", 1)
        if not version:
            raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID)
    parts = name.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID)
    namespace, design = parts

    _validate_design_name(namespace, design, design_ref)

    if version is not None:
        try:
            _SEMVER_ADAPTER.validate_python(version)
        except ValidationError as exc:
            raise SDKError(f"Invalid design ref: {design_ref}", code=ExitKind.INVALID) from exc

    return namespace, design, version


def _validate_namespace_name(namespace: str) -> None:
    try:
        _NAMESPACE_NAME_ADAPTER.validate_python(namespace)
    except ValidationError as exc:
        raise SDKError(f"Invalid namespace: {namespace}", code=ExitKind.INVALID) from exc


def _validate_design_name(namespace: str, design: str, raw_ref: str) -> None:
    try:
        _DESIGN_NAME_ADAPTER.validate_python(f"{namespace}/{design}")
    except ValidationError as exc:
        raise SDKError(f"Invalid design ref: {raw_ref}", code=ExitKind.INVALID) from exc


def _validate_semver(version: str) -> None:
    try:
        _SEMVER_ADAPTER.validate_python(version)
    except ValidationError as exc:
        raise SDKError(f"Invalid version: {version}", code=ExitKind.INVALID) from exc


def _validate_stats_date_range(from_date: str | None, to_date: str | None) -> None:
    parsed_from: date | None = None
    parsed_to: date | None = None

    if from_date:
        try:
            parsed_from = date.fromisoformat(from_date)
        except ValueError as exc:
            raise SDKError(f"Invalid from_date: {from_date}. Use YYYY-MM-DD.", code=ExitKind.INVALID) from exc

    if to_date:
        try:
            parsed_to = date.fromisoformat(to_date)
        except ValueError as exc:
            raise SDKError(f"Invalid to_date: {to_date}. Use YYYY-MM-DD.", code=ExitKind.INVALID) from exc

    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise SDKError("Invalid date range: from_date must be <= to_date.", code=ExitKind.INVALID)


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _sum_recent(series: list[StatsSeriesItem], size: int) -> int:
    if not series:
        return 0
    ordered = sorted(series, key=lambda item: item.date)
    return sum(item.downloads for item in ordered[-size:])


# ---------------------------------------------------------------------------
# Design index / manifest helpers
# ---------------------------------------------------------------------------


def _find_manifest_path(directory: Path) -> Path:
    for candidate in ("manifest.yaml", "manifest.yml", "manifest.json"):
        path = directory / candidate
        if path.exists():
            return path
    raise SDKError(f"Manifest not found in {directory}", code=ExitKind.INVALID)


def _extract_artifact_refs(manifest: PlatformManifest) -> list[_ArtifactRef]:
    refs: list[_ArtifactRef] = []
    artifacts = getattr(manifest, "artifacts", None)
    if artifacts is None:
        return refs

    for field_name in type(artifacts).model_fields:
        value = getattr(artifacts, field_name, None)
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                if hasattr(item, "file"):
                    refs.append(item)
        elif hasattr(value, "file"):
            refs.append(value)

    return refs


# ---------------------------------------------------------------------------
# Exit code helpers
# ---------------------------------------------------------------------------


def _registry_error_kind(exc: RegistryError) -> FailureKind:
    """Map a RegistryError to its semantic FailureKind (thin alias for exc.kind).

    Kept for backward compatibility; classification now lives on the error
    (client core). New code should use ``exc.kind`` directly.
    """
    return exc.kind


# ---------------------------------------------------------------------------
# Namespace / quota helpers
# ---------------------------------------------------------------------------


def _default_namespace_from_scopes(scopes: list[str]) -> str | None:
    namespaces: set[str] = set()
    for scope in scopes:
        if not scope.startswith("ns:"):
            continue
        parts = scope.split(":")
        if len(parts) >= 3 and parts[1]:
            namespaces.add(parts[1])
    if len(namespaces) == 1:
        return next(iter(namespaces))
    return None


def _quota_warning_message(response: QuotaResponse) -> str | None:
    if response.storage.used_percent >= 80:
        return "上限に近づいています"
    if response.designs.limit > 0 and (response.designs.used / response.designs.limit * 100) >= 80:
        return "上限に近づいています"
    return None


def _normalize_base_version(namespace: str, design: str, base: str) -> str:
    if "/" not in base:
        return base

    base_namespace, base_design, base_version = _parse_design_ref(base)
    if (base_namespace, base_design) != (namespace, design):
        raise SDKError(f"Base ref must target {namespace}/{design}: {base}", code=ExitKind.INVALID)
    return base_version
