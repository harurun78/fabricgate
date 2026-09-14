"""Pull orchestration for `fabricgate pull` — download, dependency resolution,
shell auto-download, attestation, and cache registration.

This is the client-core counterpart to :mod:`fabricgate.client.publisher`
(push assembly). It owns the multi-step pull flow over a
:class:`~fabricgate.client.registry_client.RegistryClient` so both the CLI and
the language SDK can reuse it. It raises client-layer exceptions only and never
maps to process exit codes (that is the caller's / CLI's concern).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fabricgate.client import cache
from fabricgate.client.publisher import _extract_artifact_refs
from fabricgate.client.registry_client import RegistryClientProtocol, RegistryError
from fabricgate.client.resolver import resolve_platform_detailed
from fabricgate.client.validator import verify_artifact
from fabricgate.models.api.errors import ErrorCode
from fabricgate.models.design_index import DesignIndex
from fabricgate.models.platform_manifest import parse_platform_manifest


class PullError(Exception):
    """Base class for client-side pull failures."""


class IntegrityError(PullError):
    """Raised when a downloaded artifact fails validation (digest / filename)."""


class AttestationError(PullError):
    """Raised when cosign attestation verification fails."""


class AttestationUnavailableError(PullError):
    """Raised when attestation is requested but cosign is not installed."""


@dataclass
class PullOutcome:
    """Result of a pull, decoupled from any presentation model."""

    name: str
    version: str
    platform: str
    path: str
    artifacts: list[str] = field(default_factory=list)
    cached: bool = False
    dependencies: list[str] = field(default_factory=list)
    shell: str | None = None
    deprecated_warning: str | None = None
    fallback_from: str | None = None
    """Originally requested platform when generic family fallback was used."""


def _version_detail_to_index(data: dict[str, Any]) -> DesignIndex:
    # Strip API-only enrichment fields (artifacts, attestation) that are not
    # part of the DesignIndex schema
    if "platforms" in data:
        for p in data["platforms"]:
            p.pop("artifacts", None)
            p.pop("attestation", None)
    return DesignIndex.model_validate(data)


def _validate_artifact_filename(artifact_name: str, *, context: str) -> Path:
    """Return the safe single-segment path for *artifact_name* or raise.

    Rejects empty, absolute, traversal, or multi-segment names.
    """
    artifact_path_obj = Path(artifact_name)
    if (
        not artifact_name
        or artifact_path_obj.is_absolute()
        or ".." in artifact_path_obj.parts
        or len(artifact_path_obj.parts) != 1
    ):
        raise IntegrityError(f"Invalid artifact filename in {context}: {artifact_name!r}")
    return artifact_path_obj


def _resolve_and_download_deps(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    device: str,
    runtime: str,
    target_dir: Path,
    verify_digests: bool,
    *,
    include_optional: bool = False,
) -> list[str]:
    """Resolve dependencies and download them into deps/ subdirectory.

    Returns list of dependency refs (``ns/design:version``) that were downloaded.
    """
    try:
        deps_resp = client.get_dependencies(
            namespace,
            design,
            version,
            device,
            runtime,
            include_optional=include_optional,
        )
    except RegistryError as exc:
        if exc.status_code == 409:
            error_code = exc.error.error.code if exc.error else ""
            if error_code == "DEPENDENCY_UNRESOLVABLE":
                raise
        if exc.status_code == 404:
            # No dependencies endpoint or no deps — not an error
            return []
        raise

    if not deps_resp.dependencies:
        return []

    dep_refs: list[str] = []
    deps_dir = target_dir / "deps"
    deps_dir.mkdir(parents=True, exist_ok=True)

    # Dependencies come in topological order from server
    for dep in deps_resp.dependencies:
        dep_ns, dep_design = str(dep.name).split("/", 1)
        dep_version = str(dep.resolved_version)
        dep_device, dep_runtime = str(dep.platform).split("/", 1)
        dep_ref = f"{dep.name}:{dep.resolved_version}"

        dep_dirname = f"{dep_ns}-{dep_design}-{dep_version}"
        dep_dir = deps_dir / dep_dirname
        dep_dir.mkdir(parents=True, exist_ok=True)

        # Download manifest
        manifest_bytes = client.get_platform_manifest_bytes(
            dep_ns,
            dep_design,
            dep_version,
            dep_device,
            dep_runtime,
        )
        (dep_dir / "manifest.yaml").write_bytes(manifest_bytes)
        manifest = parse_platform_manifest(manifest_bytes.decode("utf-8"))

        # Download artifacts
        for artifact in _extract_artifact_refs(manifest):
            artifact_name = str(artifact.file)
            artifact_path_obj = _validate_artifact_filename(artifact_name, context="dependency manifest")
            artifact_bytes = client.download_artifact(
                dep_ns,
                dep_design,
                dep_version,
                dep_device,
                dep_runtime,
                artifact_name,
            )
            artifact_path = dep_dir / artifact_path_obj
            artifact_path.write_bytes(artifact_bytes)
            if verify_digests and not verify_artifact(artifact_path, artifact.sha256):
                raise IntegrityError(f"Digest mismatch for dependency artifact {artifact_name}")

        dep_refs.append(dep_ref)

    return dep_refs


def _maybe_download_shell(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    device: str,
    runtime: str,
    target_dir: Path,
    verify_digests: bool,
    *,
    no_shell: bool = False,
) -> str | None:
    """Download the static shell for a partial bitstream if applicable.

    Returns the shell ref string if downloaded, or None.
    """
    if no_shell:
        # Skip shell download entirely — caller handles the warning output
        return None

    try:
        shell_resp = client.get_shell(namespace, design, version, device, runtime)
    except RegistryError as exc:
        if exc.status_code == 404:
            # No shell dependency — this is normal for full bitstreams
            return None
        if exc.status_code == 422 and exc.error is not None and exc.error.error.code == ErrorCode.NOT_A_PARTIAL:
            # Design is not a partial bitstream — no shell needed
            return None
        raise
    shell_info = shell_resp.shell
    shell_ref = f"{shell_info.name}:{shell_info.version}"

    shell_dirname = f"{str(shell_info.name).replace('/', '-')}-{shell_info.version}"
    shell_dir = target_dir / "shell" / shell_dirname
    shell_dir.mkdir(parents=True, exist_ok=True)

    # Download shell artifacts via pull_url or direct download
    shell_ns, shell_design = str(shell_info.name).split("/", 1)
    shell_board = shell_info.board
    shell_runtime = shell_info.runtime

    manifest_bytes = client.get_platform_manifest_bytes(
        shell_ns,
        shell_design,
        shell_info.version,
        shell_board,
        shell_runtime,
    )
    (shell_dir / "manifest.yaml").write_bytes(manifest_bytes)
    manifest = parse_platform_manifest(manifest_bytes.decode("utf-8"))

    for artifact in _extract_artifact_refs(manifest):
        artifact_name = str(artifact.file)
        artifact_path_obj = _validate_artifact_filename(artifact_name, context="shell manifest")
        artifact_bytes = client.download_artifact(
            shell_ns,
            shell_design,
            shell_info.version,
            shell_board,
            shell_runtime,
            artifact_name,
        )
        artifact_path = shell_dir / artifact_path_obj
        artifact_path.write_bytes(artifact_bytes)
        if verify_digests and not verify_artifact(artifact_path, artifact.sha256):
            raise IntegrityError(f"Digest mismatch for shell artifact {artifact_name}")

    return shell_ref


def _verify_attestation(target_dir: Path, artifact_files: list[str]) -> None:
    """Verify cosign attestation for downloaded artifacts.

    TODO: Add --key / --certificate-identity / --certificate-oidc-issuer
    parameters for proper keyless or key-based verification.
    """
    if not shutil.which("cosign"):
        raise AttestationUnavailableError("cosign is not installed. Install cosign to use --verify-attestation.")

    for filename in artifact_files:
        artifact_path = target_dir / filename
        result = subprocess.run(
            ["cosign", "verify-blob", str(artifact_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise AttestationError(f"Attestation verification failed for {filename}: {result.stderr.strip()}")


def pull_design(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    *,
    platform: str | None = None,
    output: str | Path | None = None,
    verify_digests: bool = True,
    cache_dir: str | Path | None = None,
    no_deps: bool = False,
    deps_only: bool = False,
    include_optional_deps: bool = False,
    no_shell: bool = False,
    verify_attestation: bool = False,
) -> PullOutcome:
    """Download a platform-specific build of a design and its dependencies.

    Raises client-layer exceptions (:class:`PullError` subclasses,
    :class:`RegistryError`, :class:`~fabricgate.client.resolver.ResolutionError`,
    ``OSError``); callers map these to messages / exit codes.
    """
    version_detail = client.get_version(namespace, design, version)

    # --- Deprecated warning ---
    deprecated_warning: str | None = None
    if version_detail.deprecated:
        msg = f"{version_detail.name}:{version_detail.version} is deprecated."
        if version_detail.successor:
            msg += f" Use {version_detail.successor} instead."
        if version_detail.deprecation_message:
            msg += f" {version_detail.deprecation_message}"
        deprecated_warning = msg

    index = _version_detail_to_index(version_detail.model_dump(by_alias=True))
    resolution = resolve_platform_detailed(index, platform)
    selected = resolution.entry
    board_id, runtime = selected.platform.split("/", 1)

    target_dir = Path(output) if output is not None else Path.cwd() / f"{design}-{version}"
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files: list[str] = []

    # --- Download root design (unless deps_only) ---
    if not deps_only:
        manifest_bytes = client.get_platform_manifest_bytes(namespace, design, version, board_id, runtime)
        manifest = parse_platform_manifest(manifest_bytes.decode("utf-8"))

        (target_dir / "manifest.yaml").write_bytes(manifest_bytes)

        for artifact in _extract_artifact_refs(manifest):
            artifact_name = str(artifact.file)
            artifact_path_obj = _validate_artifact_filename(artifact_name, context="manifest")
            artifact_bytes = client.download_artifact(namespace, design, version, board_id, runtime, artifact_name)
            artifact_path = target_dir / artifact_path_obj
            artifact_path.write_bytes(artifact_bytes)
            downloaded_files.append(artifact_name)
            if verify_digests and not verify_artifact(artifact_path, artifact.sha256):
                raise IntegrityError(f"Digest mismatch for {artifact_name}")

        # --- Attestation verification ---
        if verify_attestation:
            _verify_attestation(target_dir, downloaded_files)

    # --- Dependency resolution ---
    dep_refs: list[str] = []
    if not no_deps:
        dep_refs = _resolve_and_download_deps(
            client,
            namespace,
            design,
            version,
            board_id,
            runtime,
            target_dir,
            verify_digests,
            include_optional=include_optional_deps,
        )

    # --- Shell auto-download ---
    shell_ref: str | None = None
    if not deps_only:
        shell_ref = _maybe_download_shell(
            client,
            namespace,
            design,
            version,
            board_id,
            runtime,
            target_dir,
            verify_digests,
            no_shell=no_shell,
        )

    if cache_dir is not None and not deps_only:
        cache.store(
            version_detail.name,
            version_detail.version,
            selected.platform,
            selected.digest,
            target_dir,
            Path(cache_dir),
        )

    return PullOutcome(
        name=version_detail.name,
        version=version_detail.version,
        platform=selected.platform,
        path=str(target_dir),
        artifacts=downloaded_files,
        cached=False,
        dependencies=dep_refs,
        shell=shell_ref,
        deprecated_warning=deprecated_warning,
        fallback_from=resolution.fallback_from,
    )
