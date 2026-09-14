"""CLI / SDK specific models."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import Field

from fabricgate.models.common import (
    DesignName,
    FabricGateModel,
    PlatformId,
    SemVer,
    SHA256Digest,
    SpdxExpression,
)
from fabricgate.models.design_index import PlatformEntry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RegistryConfig(FabricGateModel):
    """CLI configuration (``~/.fabricgate/config.yaml``)."""

    registry: str = "https://registry.fabricgate.dev/api/v1"
    platform: PlatformId | None = None
    cache_dir: str = "~/.fabricgate/cache"


class Credentials(FabricGateModel):
    """Authentication credentials.

    Stored in OS keychain (``keyring`` library) when available,
    otherwise ``~/.fabricgate/credentials.json`` (mode 0600).
    """

    registry: str
    token: str
    expires_at: datetime
    scopes: list[str]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheEntry(FabricGateModel):
    """Single entry in the local cache index."""

    name: DesignName
    version: SemVer
    platform: PlatformId
    path: str
    pulled_at: datetime
    digest: SHA256Digest


class CacheIndex(FabricGateModel):
    """Cache index (``~/.fabricgate/cache/index.json``)."""

    entries: list[CacheEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SDK return values
# ---------------------------------------------------------------------------


class PullResult(FabricGateModel):
    """Return value of ``fabricgate.pull()``."""

    name: DesignName
    version: SemVer
    platform: PlatformId
    path: str
    artifacts: list[str]
    cached: bool
    dependencies: list[str] = Field(default_factory=list)
    shell: str | None = None
    deprecated_warning: str | None = None
    fallback_from: str | None = None
    """Originally requested platform when generic family fallback was used."""


class VerificationItem(FabricGateModel):
    """One verified artifact entry."""

    file: str
    sha256: str
    verified: bool


class VerificationResult(FabricGateModel):
    """Return value of ``fabricgate.verify()``."""

    design_ref: str
    platform: PlatformId
    directory: str
    artifacts: list[VerificationItem]


class DesignInfo(FabricGateModel):
    """Return value of ``fabricgate.info()``."""

    name: DesignName
    version: SemVer
    summary: str | None = None
    license: SpdxExpression | None = None
    author: str | None = None
    repository: str | None = None
    tags: list[str] = Field(default_factory=list)
    platforms: Sequence[PlatformEntry]


class SearchResult(FabricGateModel):
    """One element of ``fabricgate.search()`` results."""

    name: DesignName
    version: SemVer
    summary: str | None = None
    platforms: list[PlatformId]


class LoginResult(FabricGateModel):
    """Return value of ``fabricgate.login()``."""

    registry: str
    storage: str


class PushResult(FabricGateModel):
    """Return value of ``fabricgate.push()``."""

    name: DesignName
    version: SemVer
    platforms: list[PlatformId]
    published_at: datetime
    quota_warning: str | None = None
    sha_warning: str | None = None


class TokenCreateResult(FabricGateModel):
    """Return value of ``fabricgate.token_create()``."""

    id: int
    name: str
    key: str
    scopes: list[str]
    expires_at: datetime | None = None


class TokenInfo(FabricGateModel):
    """Single API key in ``fabricgate.token_list()`` results."""

    id: int
    name: str
    scopes: list[str]
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class WebhookCreateResult(FabricGateModel):
    """Return value of ``fabricgate.webhook_create()``."""

    id: int
    url: str
    events: list[str]
    design: str | None = None
    secret: str
    status: str
    created_at: datetime


class WebhookItem(FabricGateModel):
    """Single webhook in ``fabricgate.webhook_list()`` results."""

    id: int
    url: str
    events: list[str]
    design: str | None = None
    status: str
    last_delivered_at: datetime | None = None
    created_at: datetime


class WebhookTestResult(FabricGateModel):
    """Return value of ``fabricgate.webhook_test()``."""

    delivered: bool
    status_code: int
    duration_ms: int


class WebhookDeliveryItem(FabricGateModel):
    """Single delivery in ``fabricgate.webhook_deliveries()`` results."""

    id: str
    event: str
    status_code: int
    duration_ms: int
    delivered_at: datetime
    redelivery: bool = False


class YankResult(FabricGateModel):
    """Return value of a single ``fabricgate.yank()`` call."""

    name: DesignName
    version: SemVer
    yanked: bool = True
    yanked_reason: str


class DeprecateResult(FabricGateModel):
    """Return value of a single ``fabricgate.deprecate()`` call."""

    name: DesignName
    version: SemVer
    deprecated: bool
    deprecation_message: str | None = None
    successor: str | None = None


class LicenseCheckToolReq(FabricGateModel):
    """Single tool requirement in ``fabricgate.license_check()`` results."""

    tool: str
    min_version: str | None = None
    edition: str | None = None
    required: bool = True
    note: str | None = None


class LicenseCheckVerdict(FabricGateModel):
    """Check result in ``fabricgate.license_check()``."""

    tool: str
    edition: str | None = None
    meets_requirements: bool
    notes: list[str]


class LicenseCheckInfo(FabricGateModel):
    """Return value of ``fabricgate.license_check()``."""

    design: str
    version: str
    tool_requirements: list[LicenseCheckToolReq]
    check: LicenseCheckVerdict | None = None
    disclaimer: str = (
        "FabricGate provides toolchain metadata only. License compliance is the publisher's and user's responsibility."
    )


class StatsSeriesItem(FabricGateModel):
    """Single plotted point for ``fabricgate stats`` output."""

    date: str
    downloads: int


class StatsTopDesign(FabricGateModel):
    """Top design entry for namespace stats."""

    name: DesignName
    total_downloads: int


class DesignStatsInfo(FabricGateModel):
    """Return value of design/version mode in ``fabricgate.stats()``."""

    name: DesignName
    version: str | None = None
    total_downloads: int
    period: str
    series: list[StatsSeriesItem]
    last_7d: int
    last_30d: int


class NamespaceStatsInfo(FabricGateModel):
    """Return value of namespace mode in ``fabricgate.stats()``."""

    namespace: str
    total_downloads: int
    top_designs: list[StatsTopDesign]
    last_7d: int
    last_30d: int


class WatchResult(FabricGateModel):
    """Return value of ``fabricgate.watch()``."""

    design_name: str
    """Fully-qualified design name (``namespace/design``)."""

    new_version_found: bool
    """``True`` if at least one version newer than *since_version* was found."""

    latest_version: str | None = None
    """The highest non-yanked version currently published."""

    new_versions: list[str] = Field(default_factory=list)
    """All versions newer than *since_version* that match filters, newest first."""

    platforms: list[str] = Field(default_factory=list)
    """Platforms available in the newest matching version."""
