"""Platform Manifest model definitions.

Supports three runtimes via a discriminated union on the ``runtime`` field:
- ``pynq``: PYNQ Overlay-based designs
- ``linux-fpgamgr``: Linux FPGA Manager designs
- ``nanopynq``: MCU + external FPGA (Phase 3)
"""

import logging
import posixpath
from typing import Annotated, Literal, Union

import yaml
from pydantic import ConfigDict, Discriminator, Field, Tag, TypeAdapter, model_validator

from fabricgate.models.common import (
    DesignName,
    DesignRef,
    FabricGateModel,
    PlatformId,
    SemVer,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bitstream container format (ADR-011)
# ---------------------------------------------------------------------------
#
# The container format has no type dimension in the contract: the file
# extension of ``ArtifactRef.file`` is authoritative. At publish time the
# extension is checked against a per-runtime allowlist of known extensions;
# unknown extensions produce a WARNING only (never a rejection). The allowlist
# is an operational value, not part of the public contract — new formats
# (e.g. ``.pdi`` / ``.rbf``) only require updating this dict and the docs.

KNOWN_BITSTREAM_EXTENSIONS: dict[str, frozenset[str]] = {
    "pynq": frozenset({".bit"}),
    "linux-fpgamgr": frozenset({".bit", ".bin"}),
    # platform-manifest-schema.md §5.2: nanopynq's format is `.bin` (raw
    # bitstream), not `.bit` — so `.bit` should surface the ADR-011 warning.
    "nanopynq": frozenset({".bin"}),
}


def _warn_unknown_bitstream_extension(runtime: str, filename: str) -> None:
    """Log a WARNING when the bitstream extension is outside the runtime allowlist.

    ADR-011: warning only — the manifest is never rejected for its extension.
    """
    allowlist = KNOWN_BITSTREAM_EXTENSIONS.get(runtime)
    if allowlist is None:
        return
    extension = posixpath.splitext(filename)[1].lower()
    if extension not in allowlist:
        logger.warning(
            "Bitstream file '%s' has extension '%s' outside the known allowlist for runtime '%s' (%s) "
            "— accepted anyway (ADR-011)",
            filename,
            extension,
            runtime,
            ", ".join(sorted(allowlist)),
        )


# ---------------------------------------------------------------------------
# Shared artifact / interface types
# ---------------------------------------------------------------------------


class ArtifactRef(FabricGateModel):
    """Reference to a single artifact file."""

    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KernelModule(FabricGateModel):
    """Kernel module reference (linux-fpgamgr)."""

    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    module_name: str


class Interface(FabricGateModel):
    """Declared IP interface (informational)."""

    name: str
    type: str
    base: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Dependency types
# ---------------------------------------------------------------------------


class Dependency(FabricGateModel):
    """Platform Manifest dependency entry."""

    name: DesignName
    version: str = Field(
        pattern=r"^(\*|[~^]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)([\s<>=!]+.+)?)$",
        max_length=256,
    )
    platform: PlatformId | None = None
    optional: bool = False


class ResolvedDependency(FabricGateModel):
    """Resolved dependency entry (API response / SDK internal)."""

    name: DesignName
    resolved_version: SemVer
    platform: PlatformId
    optional: bool
    depth: int = Field(ge=1, le=100)
    required_by: str = Field(max_length=256)


class ShellDependency(FabricGateModel):
    """PR bitstream static shell dependency (exact version match only).

    ``sha256`` is the mandatory ADR-009 pin: the SHA-256 of the referenced
    shell's distributed bitstream artifact on the same platform.
    """

    name: DesignName
    version: str = Field(
        pattern=r"^=\d+\.\d+\.\d+$",
        max_length=64,
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )


class ToolRequirement(FabricGateModel):
    """Tool requirement metadata (informational)."""

    tool: str = Field(
        pattern=r"^[a-z][a-z0-9-]*$",
        max_length=64,
    )
    min_version: str | None = Field(default=None, max_length=64)
    edition: str | None = Field(default=None, max_length=64)
    required: bool = True
    note: str | None = Field(default=None, max_length=256)


class Attestation(FabricGateModel):
    """Sigstore / cosign attestation bundle reference."""

    bundle: str = Field(
        pattern=r"^[A-Za-z0-9._-]{1,256}$",
    )
    transparency_log_url: str = Field(
        pattern=r"^https://",
        max_length=512,
    )


# ---------------------------------------------------------------------------
# Runtime: pynq
# ---------------------------------------------------------------------------


class PynqArtifacts(FabricGateModel):
    """Artifact set for the ``pynq`` runtime."""

    bitstream: ArtifactRef
    hwh: ArtifactRef
    dtbo: ArtifactRef | None = None


class PynqManifest(FabricGateModel):
    """Platform Manifest — pynq runtime."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_: str = Field(
        alias="schema",
        default="fabricgate-platform/v1",
        pattern=r"^fabricgate-platform/v1$",
    )
    runtime: Literal["pynq"] = "pynq"
    board: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    device_family: str | None = None
    design_ref: DesignRef
    artifacts: PynqArtifacts
    pynq_version: str | None = None
    bitstream_type: str | None = Field(
        default=None,
        pattern=r"^(shell|partial)$",
    )
    status: Literal["deprecated", "yanked"] | None = None
    design_portability: Literal["axi-only", "board-specific", "io-constrained"] | None = None
    shell_dependency: ShellDependency | None = None
    tool_requirements: list[ToolRequirement] = Field(default_factory=list)
    attestation: Attestation | None = None
    interfaces: list[Interface] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_shell_dependency_consistency(self) -> "PynqManifest":
        """Validate bitstream_type / shell_dependency consistency."""
        if self.bitstream_type == "partial" and self.shell_dependency is None:
            raise ValueError("shell_dependency is required when bitstream_type is 'partial'")
        if self.bitstream_type != "partial" and self.shell_dependency is not None:
            raise ValueError("shell_dependency must not be set when bitstream_type is not 'partial'")
        return self

    @model_validator(mode="after")
    def warn_unknown_bitstream_extension(self) -> "PynqManifest":
        """ADR-011: WARNING (not rejection) for unknown bitstream container extensions."""
        _warn_unknown_bitstream_extension(self.runtime, self.artifacts.bitstream.file)
        return self


# ---------------------------------------------------------------------------
# Runtime: linux-fpgamgr
# ---------------------------------------------------------------------------


class HealthCheck(FabricGateModel):
    """Post-load health check definition."""

    type: str
    params: dict[str, str]


class PostLoad(FabricGateModel):
    """Actions to execute after FPGA programming."""

    services: list[str] = Field(default_factory=list)
    health_check: HealthCheck | None = None


class LinuxFpgamgrArtifacts(FabricGateModel):
    """Artifact set for the ``linux-fpgamgr`` runtime."""

    bitstream: ArtifactRef
    dtbo: ArtifactRef | None = None
    modules: list[KernelModule] = Field(default_factory=list)


class LinuxFpgamgrManifest(FabricGateModel):
    """Platform Manifest — linux-fpgamgr runtime."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_: str = Field(
        alias="schema",
        default="fabricgate-platform/v1",
        pattern=r"^fabricgate-platform/v1$",
    )
    runtime: Literal["linux-fpgamgr"] = "linux-fpgamgr"
    board: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    device_family: str | None = None
    design_ref: DesignRef
    artifacts: LinuxFpgamgrArtifacts
    kernel_version: str | None = None
    post_load: PostLoad | None = None
    bitstream_type: str | None = Field(
        default=None,
        pattern=r"^(shell|partial)$",
    )
    status: Literal["deprecated", "yanked"] | None = None
    design_portability: Literal["axi-only", "board-specific", "io-constrained"] | None = None
    shell_dependency: ShellDependency | None = None
    tool_requirements: list[ToolRequirement] = Field(default_factory=list)
    attestation: Attestation | None = None
    interfaces: list[Interface] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_shell_dependency_consistency(self) -> "LinuxFpgamgrManifest":
        """Validate bitstream_type / shell_dependency consistency."""
        if self.bitstream_type == "partial" and self.shell_dependency is None:
            raise ValueError("shell_dependency is required when bitstream_type is 'partial'")
        if self.bitstream_type != "partial" and self.shell_dependency is not None:
            raise ValueError("shell_dependency must not be set when bitstream_type is not 'partial'")
        return self

    @model_validator(mode="after")
    def warn_unknown_bitstream_extension(self) -> "LinuxFpgamgrManifest":
        """ADR-011: WARNING (not rejection) for unknown bitstream container extensions."""
        _warn_unknown_bitstream_extension(self.runtime, self.artifacts.bitstream.file)
        return self


# ---------------------------------------------------------------------------
# Runtime: nanopynq (Phase 3)
# ---------------------------------------------------------------------------


class Register(FabricGateModel):
    """Register definition for nanopynq IP block."""

    offset: str
    width: int


class Stream(FabricGateModel):
    """Stream definition for nanopynq IP block."""

    dir: str
    mtu: int


class IpBlock(FabricGateModel):
    """IP block definition (replaces .hwh for MCU context)."""

    base: str
    registers: dict[str, Register] = Field(default_factory=dict)
    streams: dict[str, Stream] = Field(default_factory=dict)


class NanopynqArtifacts(FabricGateModel):
    """Artifact set for the ``nanopynq`` runtime."""

    bitstream: ArtifactRef


class NanopynqManifest(FabricGateModel):
    """Platform Manifest — nanopynq runtime (Phase 3)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_: str = Field(
        alias="schema",
        default="fabricgate-platform/v1",
        pattern=r"^fabricgate-platform/v1$",
    )
    runtime: Literal["nanopynq"] = "nanopynq"
    board: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    device_family: str | None = None
    design_ref: DesignRef
    artifacts: NanopynqArtifacts
    transport: str
    mtu: int
    ips: dict[str, IpBlock] = Field(default_factory=dict)
    mcu: str | None = None
    bitstream_type: str | None = Field(
        default=None,
        pattern=r"^(shell|partial)$",
    )
    status: Literal["deprecated", "yanked"] | None = None
    design_portability: Literal["axi-only", "board-specific", "io-constrained"] | None = None
    shell_dependency: ShellDependency | None = None
    tool_requirements: list[ToolRequirement] = Field(default_factory=list)
    attestation: Attestation | None = None
    interfaces: list[Interface] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_shell_dependency_consistency(self) -> "NanopynqManifest":
        """Validate bitstream_type / shell_dependency consistency."""
        if self.bitstream_type == "partial" and self.shell_dependency is None:
            raise ValueError("shell_dependency is required when bitstream_type is 'partial'")
        if self.bitstream_type != "partial" and self.shell_dependency is not None:
            raise ValueError("shell_dependency must not be set when bitstream_type is not 'partial'")
        return self

    @model_validator(mode="after")
    def warn_unknown_bitstream_extension(self) -> "NanopynqManifest":
        """ADR-011: WARNING (not rejection) for unknown bitstream container extensions."""
        _warn_unknown_bitstream_extension(self.runtime, self.artifacts.bitstream.file)
        return self


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

PlatformManifest = Annotated[
    Union[  # noqa: UP007 — Union required for TypeAdapter at runtime
        Annotated[PynqManifest, Tag("pynq")],
        Annotated[LinuxFpgamgrManifest, Tag("linux-fpgamgr")],
        Annotated[NanopynqManifest, Tag("nanopynq")],
    ],
    Discriminator("runtime"),
]
"""Union of all runtime manifests, discriminated by the ``runtime`` field."""

_platform_manifest_adapter: TypeAdapter[PlatformManifest] = TypeAdapter(PlatformManifest)


def parse_platform_manifest(content: str) -> PlatformManifest:
    """Parse a Platform Manifest from YAML, selecting the correct runtime model."""
    data = yaml.safe_load(content)
    return _platform_manifest_adapter.validate_python(data)
