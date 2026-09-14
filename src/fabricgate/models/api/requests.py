"""API request models."""

from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field, field_validator

from fabricgate.models.common import (
    FabricGateModel,
    NamespaceName,
    PlatformId,
    SemVer,
    reject_unsafe_html,
)

# ---------------------------------------------------------------------------
# Literal types
# ---------------------------------------------------------------------------

NamespaceStatus = Literal["active", "reserved", "verified", "suspended"]
SponsorTier = Literal["platinum", "gold", "silver"]


# ---------------------------------------------------------------------------
# Auth requests
# ---------------------------------------------------------------------------


class ExternalAuthPrincipal(FabricGateModel):
    """Authenticated principal from an external IdP (MVP: GitHub only)."""

    provider: Literal["github"]
    issuer: str
    subject: str
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr | None = None


class UsernameSetupRequest(FabricGateModel):
    """First-login username setup request."""

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
    )


class ReservedNamespaceVerifyRequest(FabricGateModel):
    """Verification token input for reserved namespace unlock."""

    token: str = Field(min_length=16, max_length=256)


# ---------------------------------------------------------------------------
# Artifact upload requests
# ---------------------------------------------------------------------------


class ArtifactUploadItem(FabricGateModel):
    """One artifact the client intends to upload directly to object storage."""

    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class ArtifactUploadRequest(FabricGateModel):
    """``POST .../designs/{design}/uploads`` request."""

    artifacts: list[ArtifactUploadItem] = Field(min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Namespace requests
# ---------------------------------------------------------------------------


class NamespaceCreateRequest(FabricGateModel):
    """Create a new namespace."""

    name: NamespaceName
    display_name: str = Field(max_length=128)
    description: str = Field(default="", max_length=500)

    @field_validator("description", mode="before")
    @classmethod
    def description_no_unsafe_html(cls, v: object) -> object:
        """Reject HTML markup and JavaScript in the description field."""
        if isinstance(v, str):
            return reject_unsafe_html(v)
        return v


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


SortOrder = Literal["updated", "popular"]


class SearchParams(FabricGateModel):
    """Internal search parameter struct."""

    q: str | None = None
    platform: PlatformId | None = None
    board: str | None = None
    device_family: str | None = None
    runtime: str | None = None
    tag: str | None = None
    namespace: NamespaceName | None = None
    bitstream_type: str | None = Field(
        default=None,
        pattern=r"^(shell|partial|standalone)$",
    )
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort: SortOrder = "updated"


# ---------------------------------------------------------------------------
# Yank
# ---------------------------------------------------------------------------


class YankRequest(FabricGateModel):
    """Soft-delete (yank) a version."""

    reason: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Deprecate
# ---------------------------------------------------------------------------


class DeprecateRequest(FabricGateModel):
    """``POST .../versions/{v}/deprecate`` — mark a version as deprecated."""

    deprecation_message: str | None = Field(default=None, max_length=500)
    successor: SemVer | None = Field(
        default=None,
        description="Recommended successor version (semver string).",
    )


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


class BatchYankRequest(FabricGateModel):
    """``POST .../designs/{d}/batch-yank`` — bulk yank up to 50 versions."""

    versions: list[SemVer] = Field(..., min_length=1, max_length=50)
    reason: str = Field(default="", max_length=500)

    @field_validator("versions")
    @classmethod
    def no_duplicates(cls, v: list[SemVer]) -> list[SemVer]:
        if len(v) != len(set(v)):
            raise ValueError("versions must not contain duplicates")
        return v


class BatchDeprecateRequest(FabricGateModel):
    """``POST .../designs/{d}/batch-deprecate`` — bulk deprecate up to 50 versions."""

    versions: list[SemVer] = Field(..., min_length=1, max_length=50)
    deprecation_message: str | None = Field(default=None, max_length=500)
    successor: SemVer | None = Field(
        default=None,
        description="Recommended successor version (semver string).",
    )

    @field_validator("versions")
    @classmethod
    def no_duplicates(cls, v: list[SemVer]) -> list[SemVer]:
        if len(v) != len(set(v)):
            raise ValueError("versions must not contain duplicates")
        return v


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


class QuotaUpdateRequest(FabricGateModel):
    """``PATCH /api/v1/namespaces/{ns}/quota`` — all fields optional.

    A ``null`` value resets the field to the platform default.
    """

    storage_bytes_limit: int | None = Field(default=None, ge=1, le=10_995_116_277_760)
    versions_per_design_limit: int | None = Field(default=None, ge=1, le=100_000)
    designs_limit: int | None = Field(default=None, ge=1, le=100_000)
    file_size_limit: int | None = Field(default=None, ge=1, le=10_995_116_277_760)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class SuspendRequest(FabricGateModel):
    """``POST /api/v1/admin/users/{username}/suspend`` request."""

    reason: str = Field(default="", max_length=500)
