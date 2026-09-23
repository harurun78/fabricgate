"""API response models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from fabricgate.models.api.requests import NamespaceStatus, SponsorTier
from fabricgate.models.common import (
    ApiResponseModel,
    DesignName,
    PlatformId,
    SemVer,
    SpdxExpression,
)
from fabricgate.models.design_index import PlatformEntry
from fabricgate.models.platform_manifest import ResolvedDependency, ToolRequirement

# ---------------------------------------------------------------------------
# Artifact info (returned in version detail)
# ---------------------------------------------------------------------------


class ArtifactInfo(ApiResponseModel):
    """A single downloadable artifact file."""

    filename: str
    sha256: str
    size: int
    source: Literal["registry", "external"] | None = None
    """``"external"`` when downloads redirect to a publisher-supplied URL; absent on older servers."""


class AttestationInfo(ApiResponseModel):
    """Attestation presence exposed per platform (UI-TRUST-001).

    Presence-only signal: the registry has NOT verified the attestation;
    clients verify locally via ``fabricgate pull --verify-attestation``.
    """

    transparency_log_url: str


class ApiPlatformEntry(PlatformEntry):
    """Platform entry enriched with artifact list for API responses.

    Overrides the strict ``PlatformEntry`` (local Design Index validation)
    to tolerate unknown fields when parsed from the wire (ADR-014).
    """

    model_config = ConfigDict(extra="ignore")

    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    attestation: AttestationInfo | None = None


# ---------------------------------------------------------------------------
# Auth responses
# ---------------------------------------------------------------------------


class LoginResponse(ApiResponseModel):
    """Token issued after successful OAuth flow."""

    token: str
    expires_at: datetime
    scopes: list[str]


class UsernameSetupResponse(ApiResponseModel):
    """Result of first-login username setup."""

    username: str
    namespace: str
    created: bool = True
    created_at: datetime


# ---------------------------------------------------------------------------
# Namespace responses
# ---------------------------------------------------------------------------


class NamespaceResponse(ApiResponseModel):
    """Namespace detail."""

    name: str
    display_name: str
    description: str
    status: NamespaceStatus
    is_verified: bool = False
    reserved_until: datetime | None = None
    sponsor_tier: SponsorTier | None = None
    created_at: datetime


class NamespaceListResponse(ApiResponseModel):
    """Paginated namespace listing."""

    namespaces: list[NamespaceResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)


# ---------------------------------------------------------------------------
# Search / list responses
# ---------------------------------------------------------------------------


class DesignSummary(ApiResponseModel):
    """One row in search results / design listing."""

    name: DesignName
    latest_version: SemVer
    summary: str | None = None
    platforms: list[PlatformId]
    tags: list[str]
    bitstream_type: str | None = None
    updated_at: datetime
    version_count: int = Field(ge=0, default=0)
    download_count: int = Field(ge=0, default=0)


class SearchResponse(ApiResponseModel):
    """``GET /api/v1/designs`` response."""

    designs: list[DesignSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)


# ---------------------------------------------------------------------------
# Design detail responses
# ---------------------------------------------------------------------------


class VersionSummary(ApiResponseModel):
    """One version in design detail."""

    version: SemVer
    platforms: list[PlatformId]
    published_at: datetime
    yanked: bool = False
    deprecated: bool = False
    deprecation_message: str | None = None
    successor: str | None = None


class DesignDetailResponse(ApiResponseModel):
    """``GET /api/v1/namespaces/{ns}/designs/{d}`` response."""

    name: DesignName
    summary: str | None = None
    license: SpdxExpression | None = None
    author: str | None = None
    repository: str | None = None
    docs: str | None = None
    tags: list[str] = Field(default_factory=list)
    readme: str | None = None
    versions: list[VersionSummary]
    created_at: datetime


class VersionDetailResponse(ApiResponseModel):
    """``GET .../versions/{v}`` — Design Index as JSON with API metadata."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", default="fabricgate-index/v1")
    name: DesignName
    version: SemVer
    summary: str | None = None
    license: SpdxExpression | None = None
    author: str | None = None
    repository: str | None = None
    docs: str | None = None
    tags: list[str] = Field(default_factory=list)
    readme: str | None = None
    platforms: list[ApiPlatformEntry]
    published_at: datetime
    yanked: bool = False
    yanked_reason: str | None = None
    yanked_by: str | None = None
    deprecated: bool = False
    deprecation_message: str | None = None
    successor: str | None = None


class VersionDiffField(ApiResponseModel):
    """Single field difference for a shared platform."""

    field: str
    base: Any = None
    head: Any = None


class VersionDiffPlatform(ApiResponseModel):
    """Difference entry for one platform."""

    platform: PlatformId
    fields: list[VersionDiffField] | Literal["added", "removed"]


class VersionDiffSummary(ApiResponseModel):
    """Summary of platform-level changes between two versions."""

    platforms_added: list[PlatformId] = Field(default_factory=list)
    platforms_removed: list[PlatformId] = Field(default_factory=list)
    platforms_changed: list[PlatformId] = Field(default_factory=list)


class VersionDiffResponse(ApiResponseModel):
    """``GET .../versions/{version}/diff`` response."""

    base: str
    head: str
    summary: VersionDiffSummary
    diff: list[VersionDiffPlatform]


# ---------------------------------------------------------------------------
# Publish responses
# ---------------------------------------------------------------------------


class PublishResponse(ApiResponseModel):
    """``POST .../versions/{v}`` response."""

    name: DesignName
    version: SemVer
    platforms: list[PlatformId]
    published_at: datetime


class ArtifactUploadTicket(ApiResponseModel):
    """A presigned PUT for one artifact, or a note that it is already stored."""

    filename: str
    sha256: str
    # ``None`` when the object is already in content-addressed storage: the
    # client skips the upload and the digest still resolves at publish time.
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int | None = None


class ArtifactUploadResponse(ApiResponseModel):
    """``POST .../designs/{design}/uploads`` response."""

    uploads: list[ArtifactUploadTicket]


class PlatformAddResponse(ApiResponseModel):
    """``POST .../platforms/{device}/{runtime}`` (incremental publish)."""

    name: DesignName
    version: SemVer
    platform: PlatformId
    published_at: datetime


# ---------------------------------------------------------------------------
# Yank response
# ---------------------------------------------------------------------------


class YankResponse(ApiResponseModel):
    """``DELETE .../versions/{v}`` response."""

    name: DesignName
    version: SemVer
    yanked: bool = True
    yanked_reason: str
    yanked_by: str | None = None


class DeprecateResponse(ApiResponseModel):
    """``POST .../versions/{v}/deprecate`` response."""

    name: DesignName
    version: SemVer
    deprecated: bool
    deprecation_message: str | None = None
    successor: str | None = None


# ---------------------------------------------------------------------------
# Batch responses
# ---------------------------------------------------------------------------


class BatchResultItem(ApiResponseModel):
    """Result entry for a single version in a batch operation."""

    version: SemVer
    status: Literal["yanked", "deprecated", "skipped"]


class BatchYankResponse(ApiResponseModel):
    """``POST .../designs/{d}/batch-yank`` response."""

    name: DesignName
    results: list[BatchResultItem]


class BatchDeprecateResponse(ApiResponseModel):
    """``POST .../designs/{d}/batch-deprecate`` response."""

    name: DesignName
    results: list[BatchResultItem]


# ---------------------------------------------------------------------------
# Stats response
# ---------------------------------------------------------------------------


class RegistryStatsResponse(ApiResponseModel):
    """``GET /api/v1/stats`` — aggregate registry statistics."""

    total_designs: int = Field(ge=0)
    total_namespaces: int = Field(ge=0)
    total_versions: int = Field(ge=0)
    total_platforms: int = Field(ge=0)


class DownloadSeriesPoint(ApiResponseModel):
    """One aggregated data point in a download series."""

    date: date
    downloads: int = Field(ge=0)


class DesignStatsResponse(ApiResponseModel):
    """``GET .../designs/{design}/stats`` response."""

    name: DesignName
    total_downloads: int = Field(ge=0)
    period: Literal["daily", "weekly", "monthly"]
    series: list[DownloadSeriesPoint]


class VersionStatsResponse(ApiResponseModel):
    """``GET .../versions/{version}/stats`` response."""

    name: DesignName
    version: SemVer
    total_downloads: int = Field(ge=0)
    period: Literal["daily", "weekly", "monthly"]
    series: list[DownloadSeriesPoint]


class NamespaceTopDesign(ApiResponseModel):
    """Top design entry in namespace statistics."""

    name: DesignName
    total_downloads: int = Field(ge=0)


class NamespacePeriodDownloads(ApiResponseModel):
    """Rolling period counters in namespace statistics."""

    last_7d: int = Field(ge=0)
    last_30d: int = Field(ge=0)


class NamespaceStatsResponse(ApiResponseModel):
    """``GET /api/v1/namespaces/{namespace}/stats`` response."""

    namespace: str
    total_downloads: int = Field(ge=0)
    top_designs: list[NamespaceTopDesign]
    period_downloads: NamespacePeriodDownloads


# ---------------------------------------------------------------------------
# Quota responses  (§ 3.12)
# ---------------------------------------------------------------------------


class QuotaStorageInfo(ApiResponseModel):
    """Storage sub-object in QuotaResponse."""

    used_bytes: int = Field(ge=0)
    limit_bytes: int = Field(ge=0)
    used_percent: float = Field(ge=0)


class QuotaVersionsInfo(ApiResponseModel):
    """Versions-per-design sub-object in QuotaResponse."""

    limit: int = Field(ge=0)


class QuotaDesignsInfo(ApiResponseModel):
    """Designs sub-object in QuotaResponse."""

    used: int = Field(ge=0)
    limit: int = Field(ge=0)


class QuotaResponse(ApiResponseModel):
    """``GET /api/v1/namespaces/{ns}/quota`` response."""

    namespace: str
    storage: QuotaStorageInfo
    versions_per_design: QuotaVersionsInfo
    designs: QuotaDesignsInfo
    file_size_limit_bytes: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Dependencies response  (§ 3.13)
# ---------------------------------------------------------------------------


class DependenciesResponse(ApiResponseModel):
    """``GET .../dependencies`` — resolved dependency tree as flat list."""

    root: str
    platform: PlatformId
    dependencies: list[ResolvedDependency]


# ---------------------------------------------------------------------------
# Shell / License-check responses  (§ 3.14)
# ---------------------------------------------------------------------------


class ShellArtifactInfo(ApiResponseModel):
    """Single artifact from the referenced static shell."""

    file: str
    sha256: str
    size: int


class ShellInfo(ApiResponseModel):
    """Static shell design resolved from ``shell_dependency``."""

    name: DesignName
    version: SemVer
    board: str
    device_family: str | None = None
    runtime: str
    bitstream_type: str
    artifacts: list[ShellArtifactInfo]
    pull_url: str


class ShellResponse(ApiResponseModel):
    """``GET .../platforms/{device}/{runtime}/shell``."""

    shell: ShellInfo


class LicenseCheckResult(ApiResponseModel):
    """Result of tool/edition requirement check."""

    tool: str
    edition: str | None = None
    meets_requirements: bool
    notes: list[str]


class LicenseCheckResponse(ApiResponseModel):
    """``GET .../versions/{version}/license-check``."""

    design: DesignName
    version: SemVer
    tool_requirements: list[ToolRequirement]
    check: LicenseCheckResult | None = None
    disclaimer: str = (
        "FabricGate provides toolchain metadata only. License compliance is the publisher's and user's responsibility."
    )


# ---------------------------------------------------------------------------
# API Key responses  (§ 3.8)
# ---------------------------------------------------------------------------


class ApiKeyCreateResponse(ApiResponseModel):
    """``POST /api/v1/users/me/api-keys`` — created key with plaintext token."""

    id: int
    name: str
    key: str
    scopes: list[str]
    expires_at: datetime | None = None
    created_at: datetime


class ApiKeyInfo(ApiResponseModel):
    """Single API key entry (no plaintext token)."""

    id: int
    name: str
    scopes: list[str]
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ApiKeyListResponse(ApiResponseModel):
    """``GET /api/v1/users/me/api-keys`` response."""

    api_keys: list[ApiKeyInfo]


# ---------------------------------------------------------------------------
# Webhook responses  (§ 3.9)
# ---------------------------------------------------------------------------


class WebhookCreateResponse(ApiResponseModel):
    """``POST /api/v1/namespaces/{ns}/webhooks`` — created webhook with secret."""

    id: int
    url: str
    events: list[str]
    design: str | None = None
    secret: str
    status: str
    created_at: datetime


class WebhookInfo(ApiResponseModel):
    """Single webhook entry (no secret)."""

    id: int
    url: str
    events: list[str]
    design: str | None = None
    status: str
    last_delivered_at: datetime | None = None
    created_at: datetime


class WebhookListResponse(ApiResponseModel):
    """``GET /api/v1/namespaces/{ns}/webhooks`` response."""

    webhooks: list[WebhookInfo]


class WebhookTestResponse(ApiResponseModel):
    """``POST .../webhooks/{id}/test`` response."""

    delivered: bool
    status_code: int
    duration_ms: int


class WebhookDelivery(ApiResponseModel):
    """Single delivery log entry."""

    id: str
    event: str
    status_code: int
    duration_ms: int
    delivered_at: datetime
    redelivery: bool = False


class WebhookDeliveriesResponse(ApiResponseModel):
    """``GET .../webhooks/{id}/deliveries`` response."""

    deliveries: list[WebhookDelivery]


# ---------------------------------------------------------------------------
# Admin responses
# ---------------------------------------------------------------------------


class AdminUserEntry(ApiResponseModel):
    """Single user entry for admin user list."""

    id: int
    username: str
    email: str | None = None
    provider: str
    created_at: datetime
    suspended: bool
    suspended_at: datetime | None = None
    suspension_reason: str | None = None


class AdminUserListResponse(ApiResponseModel):
    """``GET /api/v1/admin/users`` response."""

    users: list[AdminUserEntry]
    total: int
    page: int
    per_page: int


class SuspendResponse(ApiResponseModel):
    """``POST /api/v1/admin/users/{username}/suspend`` response."""

    username: str
    suspended: bool
    suspended_at: datetime | None = None
    suspension_reason: str | None = None


class NamespaceSuspendResponse(ApiResponseModel):
    """``POST/DELETE /api/v1/admin/namespaces/{namespace}/suspend`` response."""

    namespace: str
    status: str
    suspended: bool


class AdminNamespaceEntry(ApiResponseModel):
    """Single namespace entry for admin namespace list."""

    name: str
    display_name: str
    status: str
    is_verified: bool
    design_count: int
    storage_used: int
    created_at: datetime


class AdminNamespaceListResponse(ApiResponseModel):
    """``GET /api/v1/admin/namespaces`` response."""

    namespaces: list[AdminNamespaceEntry]
    total: int
    page: int
    per_page: int


class AdminStorageTopEntry(ApiResponseModel):
    """Top namespace by storage in admin storage overview."""

    namespace: str
    storage_used: int


class AdminStorageOverview(ApiResponseModel):
    """``GET /api/v1/admin/storage`` response."""

    total_storage_used: int
    total_storage_limit: int
    namespace_count: int
    top_namespaces: list[AdminStorageTopEntry]


class MirrorSyncLogEntry(ApiResponseModel):
    """Single entry in the mirror sync log."""

    id: int
    namespace: str
    design_name: str
    version: str
    status: str
    synced_at: datetime
    error_message: str | None = None


class MirrorSyncLogResponse(ApiResponseModel):
    """``GET /api/v1/admin/mirror/sync-log`` response."""

    entries: list[MirrorSyncLogEntry]
    total: int
    page: int
    per_page: int
