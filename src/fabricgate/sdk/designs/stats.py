"""Download statistics SDK function."""

from __future__ import annotations

from typing import Literal

from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import DesignStatsInfo, NamespaceStatsInfo, StatsSeriesItem, StatsTopDesign
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _parse_design_ref_optional_version,
    _registry_error_kind,
    _sum_recent,
    _validate_namespace_name,
    _validate_stats_date_range,
)


def stats(
    design_ref: str | None = None,
    *,
    namespace: str | None = None,
    period: Literal["daily", "weekly", "monthly"] = "daily",
    from_date: str | None = None,
    to_date: str | None = None,
    version: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
) -> DesignStatsInfo | NamespaceStatsInfo:
    """Fetch download statistics for a design/version or a namespace."""
    if design_ref and namespace:
        raise SDKError("Specify either design_ref or namespace, not both.", code=ExitKind.INVALID)
    if not design_ref and not namespace:
        raise SDKError("Either design_ref or namespace is required.", code=ExitKind.INVALID)
    if period not in {"daily", "weekly", "monthly"}:
        raise SDKError(f"Invalid period: {period}", code=ExitKind.INVALID)
    _validate_stats_date_range(from_date, to_date)
    if namespace:
        _validate_namespace_name(namespace)

    try:
        with RegistryClient(base_url=registry, token=token) as client:
            if namespace:
                namespace_resp = client.get_namespace_stats(namespace)
                return NamespaceStatsInfo(
                    namespace=namespace_resp.namespace,
                    total_downloads=namespace_resp.total_downloads,
                    top_designs=[
                        StatsTopDesign(name=item.name, total_downloads=item.total_downloads)
                        for item in namespace_resp.top_designs
                    ],
                    last_7d=namespace_resp.period_downloads.last_7d,
                    last_30d=namespace_resp.period_downloads.last_30d,
                )

            parsed_namespace, design, ref_version = _parse_design_ref_optional_version(str(design_ref))
            if ref_version and version:
                raise SDKError("Version was specified in both design_ref and --version.", code=ExitKind.INVALID)
            resolved_version = version or ref_version

            if resolved_version:
                version_resp = client.get_version_stats(
                    parsed_namespace,
                    design,
                    resolved_version,
                    period=period,
                    from_date=from_date,
                    to_date=to_date,
                )
                series = [
                    StatsSeriesItem(date=point.date.isoformat(), downloads=point.downloads)
                    for point in version_resp.series
                ]
                return DesignStatsInfo(
                    name=version_resp.name,
                    version=version_resp.version,
                    total_downloads=version_resp.total_downloads,
                    period=version_resp.period,
                    series=series,
                    last_7d=_sum_recent(series, 7),
                    last_30d=_sum_recent(series, 30),
                )

            design_resp = client.get_design_stats(
                parsed_namespace,
                design,
                period=period,
                from_date=from_date,
                to_date=to_date,
            )
            series = [
                StatsSeriesItem(date=point.date.isoformat(), downloads=point.downloads) for point in design_resp.series
            ]
            return DesignStatsInfo(
                name=design_resp.name,
                version=None,
                total_downloads=design_resp.total_downloads,
                period=design_resp.period,
                series=series,
                last_7d=_sum_recent(series, 7),
                last_30d=_sum_recent(series, 30),
            )
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
