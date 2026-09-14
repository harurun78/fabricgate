"""Design Index model definitions."""

from __future__ import annotations

import logging

from pydantic import ConfigDict, Field, field_validator, model_validator

from fabricgate.models.common import (
    DesignName,
    FabricGateModel,
    PlatformId,
    SemVer,
    SHA256Digest,
    SpdxExpression,
    SpeedGrade,
    find_unknown_spdx_ids,
    reject_unsafe_html,
)
from fabricgate.models.platform_manifest import ShellDependency

logger = logging.getLogger(__name__)


class PlatformEntry(FabricGateModel):
    """A single platform entry within a Design Index."""

    platform: PlatformId
    digest: SHA256Digest
    size: int | None = Field(default=None, ge=0)
    speed_grade: SpeedGrade | None = None
    shell_dependency: ShellDependency | None = None


class DesignIndex(FabricGateModel):
    """Design Index — top-level descriptor for a versioned FPGA design.

    Lists all available platform-specific builds and provides metadata
    needed for platform resolution.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_: str = Field(
        alias="schema",
        default="fabricgate-index/v1",
        pattern=r"^fabricgate-index/v1$",
    )
    name: DesignName
    version: SemVer
    summary: str | None = Field(default=None, max_length=200)
    license: SpdxExpression | None = None
    author: str | None = None
    repository: str | None = None
    docs: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    platforms: list[PlatformEntry] = Field(min_length=1)

    @field_validator("summary", mode="before")
    @classmethod
    def summary_no_unsafe_html(cls, v: object) -> object:
        """Reject HTML markup and JavaScript in the summary field."""
        if isinstance(v, str):
            return reject_unsafe_html(v)
        return v

    @model_validator(mode="after")
    def no_duplicate_platforms(self) -> DesignIndex:
        """Reject duplicate (platform, shell_dependency) combinations."""
        seen: set[tuple[str, str]] = set()
        for entry in self.platforms:
            sd = entry.shell_dependency
            shell_key = f"{sd.name}={sd.version}" if sd else ""
            key = (entry.platform, shell_key)
            if key in seen:
                raise ValueError(f"Duplicate platform: {entry.platform}")
            seen.add(key)
        return self

    @model_validator(mode="after")
    def warn_unknown_spdx_ids(self) -> DesignIndex:
        """Log a WARNING for SPDX identifiers not in the published list."""
        if self.license is not None:
            unknown = find_unknown_spdx_ids(self.license)
            for ident in unknown:
                logger.warning(
                    "SPDX identifier '%s' is not in the published SPDX license list (license=%s)",
                    ident,
                    self.license,
                )
        return self

    # ------------------------------------------------------------------
    # YAML helpers
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialize to canonical YAML (for ``fabricgate push``)."""
        import yaml

        data = self.model_dump(by_alias=True, exclude_none=True)
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, content: str) -> DesignIndex:
        """Parse a Design Index from YAML."""
        import yaml

        data = yaml.safe_load(content)
        return cls.model_validate(data)
