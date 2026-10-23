"""Pull orchestration for `fabricgate pull` — download, dependency resolution,
shell auto-download, attestation, and cache registration.

This is the client-core counterpart to :mod:`fabricgate.client.publisher`
(push assembly). It owns the multi-step pull flow over a
:class:`~fabricgate.client.registry_client.RegistryClient` so both the CLI and
the language SDK can reuse it. It raises client-layer exceptions only and never
maps to process exit codes (that is the caller's / CLI's concern).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from fabricgate.client import cache
from fabricgate.client.publisher import _extract_artifact_refs, _is_single_filename
from fabricgate.client.registry_client import RegistryClientProtocol, RegistryError
from fabricgate.client.resolver import resolve_platform_detailed
from fabricgate.models.api.errors import ErrorCode
from fabricgate.models.design_index import DesignIndex
from fabricgate.models.platform_manifest import PlatformManifest, parse_platform_manifest


class PullError(Exception):
    """Base class for client-side pull failures."""


class IntegrityError(PullError):
    """Raised when a downloaded artifact fails validation (digest / filename)."""


class AttestationError(PullError):
    """Raised when cosign attestation verification fails."""


class AttestationUnavailableError(PullError):
    """Raised when attestation is requested but cosign is not installed."""


@dataclass(frozen=True)
class AttestationSigner:
    """Who must have signed a manifest: a public key, or a keyless certificate identity."""

    key: str | None = None
    certificate_identity: str | None = None
    certificate_oidc_issuer: str | None = None

    def __post_init__(self) -> None:
        keyless = self.certificate_identity is not None or self.certificate_oidc_issuer is not None
        if self.key is not None and keyless:
            raise ValueError("Give either an attestation key or a certificate identity and OIDC issuer, not both.")
        if self.key is None and not (self.certificate_identity and self.certificate_oidc_issuer):
            raise ValueError(
                "Attestation verification needs an attestation key, "
                "or both a certificate identity and a certificate OIDC issuer."
            )

    def cosign_args(self) -> list[str]:
        if self.key is not None:
            return ["--key", self.key]
        assert self.certificate_identity is not None and self.certificate_oidc_issuer is not None
        return [
            "--certificate-identity",
            self.certificate_identity,
            "--certificate-oidc-issuer",
            self.certificate_oidc_issuer,
        ]


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
    if not _is_single_filename(artifact_name):
        raise IntegrityError(f"Invalid artifact filename in {context}: {artifact_name!r}")
    return Path(artifact_name)


def _write_verified(path: Path, data: bytes, expected_sha256: str, *, verify: bool, label: str) -> None:
    """Write *data* to *path*, checking its digest first when *verify* is set.

    Checking before the write keeps a mismatching download from landing on disk
    under its final name or overwriting a file verified by an earlier pull.
    """
    if verify and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise IntegrityError(f"Digest mismatch for {label}")
    path.write_bytes(data)


def _verify_manifest_attestation(
    manifest_dir: Path,
    manifest: PlatformManifest,
    fetch: Callable[[str], bytes],
    signer: AttestationSigner,
    *,
    label: str,
    expected_ref: str,
    expected_runtime: str,
) -> None:
    """Check the cosign bundle that signs ``manifest_dir/manifest.yaml``.

    The bundle signs the manifest, and the manifest pins every artifact by
    sha256, so one signature covers the whole platform. Runs before any
    artifact is downloaded so nothing is written for an unsigned manifest.

    The manifest must also name the design and runtime that were requested;
    otherwise another manifest from the same signer (an older version, or a
    different design) would pass in its place.
    """
    if str(manifest.design_ref) != expected_ref or manifest.runtime != expected_runtime:
        raise AttestationError(
            f"{label} is for {manifest.design_ref} ({manifest.runtime}), expected {expected_ref} ({expected_runtime})"
        )
    if manifest.attestation is None:
        raise AttestationError(f"{label} declares no attestation bundle")
    if not shutil.which("cosign"):
        raise AttestationUnavailableError("cosign is not installed. Install cosign to use --verify-attestation.")
    bundle_name = manifest.attestation.bundle
    bundle_path = manifest_dir / _validate_artifact_filename(bundle_name, context=f"{label} attestation")
    bundle_path.write_bytes(fetch(bundle_name))
    try:
        result = subprocess.run(
            [
                "cosign",
                "verify-blob",
                str(manifest_dir / "manifest.yaml"),
                "--bundle",
                str(bundle_path),
                *signer.cosign_args(),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise AttestationError(f"Attestation verification timed out for {label}") from exc
    if result.returncode != 0:
        raise AttestationError(f"Attestation verification failed for {label}: {result.stderr.strip()}")


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
    signer: AttestationSigner | None = None,
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
        if signer is not None:
            _verify_manifest_attestation(
                dep_dir,
                manifest,
                partial(client.download_artifact, dep_ns, dep_design, dep_version, dep_device, dep_runtime),
                signer,
                label=f"dependency manifest {dep_ref}",
                expected_ref=dep_ref,
                expected_runtime=dep_runtime,
            )

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
            _write_verified(
                dep_dir / artifact_path_obj,
                artifact_bytes,
                artifact.sha256,
                verify=verify_digests,
                label=f"dependency artifact {artifact_name}",
            )

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
    signer: AttestationSigner | None = None,
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
    if signer is not None:
        _verify_manifest_attestation(
            shell_dir,
            manifest,
            partial(client.download_artifact, shell_ns, shell_design, shell_info.version, shell_board, shell_runtime),
            signer,
            label=f"shell manifest {shell_ref}",
            expected_ref=shell_ref,
            expected_runtime=shell_runtime,
        )

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
        _write_verified(
            shell_dir / artifact_path_obj,
            artifact_bytes,
            artifact.sha256,
            verify=verify_digests,
            label=f"shell artifact {artifact_name}",
        )

    return shell_ref


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
    attestation_signer: AttestationSigner | None = None,
) -> PullOutcome:
    """Download a platform-specific build of a design and its dependencies.

    With *verify_attestation*, every manifest (root, dependencies, shell) must
    carry a cosign bundle signed by *attestation_signer*.

    Raises client-layer exceptions (:class:`PullError` subclasses,
    :class:`RegistryError`, :class:`~fabricgate.client.resolver.ResolutionError`,
    ``OSError``); callers map these to messages / exit codes.
    """
    if verify_attestation and not verify_digests:
        # The signature covers the manifest only; artifacts are bound to it by digest.
        raise AttestationError(
            "Attestation verification requires digest verification (do not combine with --no-verify)."
        )
    if verify_attestation and attestation_signer is None:
        raise AttestationError(
            "Attestation verification needs an attestation key, "
            "or both a certificate identity and a certificate OIDC issuer."
        )
    signer = attestation_signer if verify_attestation else None
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
        if signer is not None:
            _verify_manifest_attestation(
                target_dir,
                manifest,
                partial(client.download_artifact, namespace, design, version, board_id, runtime),
                signer,
                label=f"manifest {namespace}/{design}:{version}",
                expected_ref=f"{namespace}/{design}:{version}",
                expected_runtime=runtime,
            )

        for artifact in _extract_artifact_refs(manifest):
            artifact_name = str(artifact.file)
            artifact_path_obj = _validate_artifact_filename(artifact_name, context="manifest")
            artifact_bytes = client.download_artifact(namespace, design, version, board_id, runtime, artifact_name)
            _write_verified(
                target_dir / artifact_path_obj,
                artifact_bytes,
                artifact.sha256,
                verify=verify_digests,
                label=artifact_name,
            )
            downloaded_files.append(artifact_name)

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
            signer=signer,
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
            signer=signer,
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
