"""Pull (download) SDK function plus local digest verification."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

import yaml
from pydantic import ValidationError

from fabricgate.client import auth, puller
from fabricgate.client.puller import (
    AttestationError,
    AttestationSigner,
    AttestationUnavailableError,
    IntegrityError,
)
from fabricgate.client.registry_client import RegistryClient
from fabricgate.client.resolver import ResolutionError
from fabricgate.client.validator import artifact_refs, is_single_filename, verify_artifact
from fabricgate.models.cli import PullResult, VerificationItem, VerificationResult
from fabricgate.models.platform_manifest import PlatformManifest, parse_platform_manifest
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _find_manifest_path,
    _parse_design_ref,
    _registry_errors,
)


def pull(
    design_ref: str,
    *,
    platform: str | None = None,
    output: str | Path | None = None,
    verify_digests: bool = True,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
    cache_dir: str | Path | None = None,
    no_deps: bool = False,
    deps_only: bool = False,
    include_optional_deps: bool = False,
    no_shell: bool = False,
    verify_attestation: bool = False,
    attestation_key: str | None = None,
    certificate_identity: str | None = None,
    certificate_oidc_issuer: str | None = None,
    on_progress: Callable[[str, int, int | None], None] | None = None,
) -> PullResult:
    """Download a platform-specific build of a design.

    With *verify_attestation*, each manifest must be signed by the given
    *attestation_key*, or by *certificate_identity* / *certificate_oidc_issuer*
    (keyless).

    With *cache_dir*, artifacts are taken from that cache when their pinned
    sha256 is there (``PullResult.cached`` is true when all root artifacts were),
    and downloaded ones are added to it. Without it, no cache is read or written.

    *on_progress* is called as ``on_progress(label, bytes_received, total_bytes)``
    while artifacts are fetched. *label* is ``"<ns>/<design>:<version> <file>"``;
    *total_bytes* is ``None`` when the size is unknown. A cached artifact is
    reported once, as complete.
    """
    if no_deps and deps_only:
        raise SDKError("--no-deps and --deps-only are mutually exclusive.", code=ExitKind.INVALID)

    signer: AttestationSigner | None = None
    if verify_attestation:
        try:
            signer = AttestationSigner(attestation_key, certificate_identity, certificate_oidc_issuer)
        except ValueError as exc:
            raise SDKError(str(exc), code=ExitKind.INVALID) from exc
    elif (attestation_key, certificate_identity, certificate_oidc_issuer) != (None, None, None):
        raise SDKError(
            "--attestation-key / --certificate-identity / --certificate-oidc-issuer require --verify-attestation.",
            code=ExitKind.INVALID,
        )

    namespace, design, version = _parse_design_ref(design_ref)

    # Resolve stored credentials when no explicit token is given, so pulls by
    # logged-in users are attributed for the organic pull rate KPI
    # (API-KPI-001). Pull stays public: no credentials (or a credential-store
    # failure) means an anonymous pull, never an error. Only store-shaped
    # failures are swallowed — OSError covers file I/O, ValueError covers
    # JSON decode / pydantic validation of a corrupt store (keyring errors
    # are already handled inside ``load_credentials``); programmer errors
    # still surface.
    effective_token = token
    if effective_token is None:
        try:
            creds = auth.load_credentials(registry)
        except (OSError, ValueError):
            creds = None
        if creds is not None:
            effective_token = creds.token

    try:
        with _registry_errors(), RegistryClient(base_url=registry, token=effective_token) as client:
            outcome = puller.pull_design(
                client,
                namespace,
                design,
                version,
                platform=platform,
                output=output,
                verify_digests=verify_digests,
                cache_dir=cache_dir,
                no_deps=no_deps,
                deps_only=deps_only,
                include_optional_deps=include_optional_deps,
                no_shell=no_shell,
                verify_attestation=verify_attestation,
                attestation_signer=signer,
                on_progress=on_progress,
            )
    except ResolutionError as exc:
        raise SDKError(str(exc), code=ExitKind.UNRESOLVABLE) from exc
    except AttestationUnavailableError as exc:
        raise SDKError(str(exc), code=ExitKind.INFRA) from exc
    except (IntegrityError, AttestationError) as exc:
        raise SDKError(str(exc), code=ExitKind.INVALID) from exc
    except OSError as exc:
        raise SDKError(str(exc), code=ExitKind.INFRA) from exc

    return PullResult(
        name=outcome.name,
        version=outcome.version,
        platform=outcome.platform,
        path=outcome.path,
        artifacts=outcome.artifacts,
        cached=outcome.cached,
        dependencies=outcome.dependencies,
        shell=outcome.shell,
        deprecated_warning=outcome.deprecated_warning,
        fallback_from=outcome.fallback_from,
    )


def verify(
    directory: str | Path,
    *,
    ref: str | None = None,
    platform: str | None = None,
    offline: bool = False,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> VerificationResult:
    """Verify a pulled design directory, with its dependencies and shell.

    First the manifest is checked against the registry: its SHA-256 must equal the
    ``digest`` of a platform of *ref* (default: the manifest's own ``design_ref``),
    or of *platform* when given. Then each artifact is checked against the manifest.
    With *offline*, only the artifacts are checked.

    Each directory under ``deps/`` and ``shell/`` is checked the same way, against the
    version its path names. The shell must also carry the artifact that the root
    manifest's ``shell_dependency`` pins.
    """
    if offline and (ref is not None or platform is not None):
        raise SDKError("--ref and --platform cannot be combined with --offline.", code=ExitKind.INVALID)
    target_dir = Path(directory)
    with nullcontext() if offline else RegistryClient(base_url=registry) as client:
        result, manifest = _verify_dir(client, target_dir, ref=ref, platform=platform)
        result.dependencies = [
            _verify_dir(client, d, path_ref=_path_ref(d))[0] for d in _pulled_dirs(target_dir, "deps")
        ]
        result.shells = [_verify_dir(client, d, path_ref=_path_ref(d))[0] for d in _pulled_dirs(target_dir, "shell")]

    # Only what the root declares itself: transitive dependencies are declared by the dependencies.
    # A checked directory's design_ref equals its path, so this sees exactly the version directories pull creates.
    pulled = {d.design_ref.split(":", 1)[0] for d in result.dependencies}
    result.missing = [
        str(dep.name) for dep in manifest.dependencies if not dep.optional and str(dep.name) not in pulled
    ]
    pin = manifest.shell_dependency
    if pin is not None:
        shell_ref = f"{pin.name}:{pin.version.removeprefix('=')}"
        shell = next((s for s in result.shells if s.design_ref == shell_ref), None)
        if shell is None and result.shells:
            # Pull only ever places the pinned version, so another shell stands in for it.
            raise SDKError(
                f"The manifest's shell_dependency pins {shell_ref}, but the shell directory holds "
                f"{', '.join(s.design_ref for s in result.shells)}.",
                code=ExitKind.INVALID,
            )
        if shell is None:
            result.missing.append(shell_ref)
        elif not any(item.sha256 == pin.sha256 for item in shell.artifacts):
            # Another genuine platform of the same shell version would pass the digest lookup.
            raise SDKError(
                f"Shell {shell_ref} has no artifact with the sha256 that the manifest's shell_dependency pins.",
                code=ExitKind.INVALID,
            )
    return result


def _pulled_dirs(target_dir: Path, kind: str) -> list[Path]:
    """Return the ``<kind>/<namespace>/<design>/<version>/`` directories that pull creates."""
    return sorted(path for path in (target_dir / kind).glob("*/*/*") if path.is_dir())


def _path_ref(directory: Path) -> str:
    """Return ``<namespace>/<design>:<version>`` from a ``.../<namespace>/<design>/<version>`` path."""
    return f"{directory.parent.parent.name}/{directory.parent.name}:{directory.name}"


def _verify_dir(
    client: RegistryClient | None,
    target_dir: Path,
    *,
    ref: str | None = None,
    platform: str | None = None,
    path_ref: str | None = None,
) -> tuple[VerificationResult, PlatformManifest]:
    """Check one pulled directory: the manifest against the registry (unless *client* is None), then the artifacts.

    *path_ref* is the version a ``deps/`` or ``shell/`` directory's path names; the
    manifest must name the same one, and it is the version checked against.
    """
    manifest_path = _find_manifest_path(target_dir)
    try:
        # One read: the bytes that are parsed are the bytes that are hashed.
        manifest_bytes = manifest_path.read_bytes()
        manifest = parse_platform_manifest(manifest_bytes.decode("utf-8"))
    except (ValidationError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SDKError(f"Invalid manifest {manifest_path}: {exc}", code=ExitKind.INVALID) from exc
    except OSError as exc:
        raise SDKError(f"Cannot read {manifest_path}: {exc}", code=ExitKind.INFRA) from exc
    if path_ref is not None:
        _parse_design_ref(path_ref)
        if str(manifest.design_ref) != path_ref:
            raise SDKError(
                f"{manifest_path} names {manifest.design_ref}, but its directory is for {path_ref}.",
                code=ExitKind.INVALID,
            )
        ref = path_ref

    checked_ref: str | None = None
    checked_platform: str | None = None
    yanked = False
    yanked_reason: str | None = None
    if client is not None:
        # A rewritten manifest can name any version, so the caller sees which one was used.
        checked_ref = ref if ref is not None else str(manifest.design_ref)
        namespace, design, version = _parse_design_ref(checked_ref)
        try:
            with _registry_errors():
                detail = client.get_version(namespace, design, version)
        except SDKError as exc:
            if exc.code == ExitKind.INFRA:
                # No silent fallback to the artifact-only check: blocking the network must not downgrade it.
                raise SDKError(f"{exc}\nUse --offline to check only the artifacts.", code=ExitKind.INFRA) from exc
            raise
        candidates = [entry for entry in detail.platforms if platform is None or str(entry.platform) == platform]
        if platform is not None and not candidates:
            available = ", ".join(str(entry.platform) for entry in detail.platforms)
            raise SDKError(
                f"Platform {platform} not found in {checked_ref}. Available: {available}", code=ExitKind.NOT_FOUND
            )
        # Not the manifest's board: a platform ID's board can differ from it (generic fallback).
        digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
        matched = next((entry for entry in candidates if str(entry.digest) == digest), None)
        if matched is None:
            where = f"platform {platform} of {checked_ref}" if platform is not None else checked_ref
            # Versions published before the registry checked the index digest may carry a stale one.
            raise SDKError(
                f"{manifest_path} does not match the registry's digest for {where}. "
                "Either the directory changed after the pull, or the registry's digest for this version is stale "
                "(use --offline to check only the artifacts).",
                code=ExitKind.INVALID,
            )
        checked_platform = str(matched.platform)
        yanked = detail.yanked
        yanked_reason = detail.yanked_reason

    results: list[VerificationItem] = []
    for artifact in artifact_refs(manifest):
        artifact_name = str(artifact.file)
        if not is_single_filename(artifact_name):
            raise SDKError(
                f"Invalid artifact filename in manifest: {artifact_name!r}",
                code=ExitKind.INVALID,
            )

        artifact_path = target_dir / artifact_name
        if not artifact_path.exists():
            raise SDKError(f"Artifact not found: {artifact_path}", code=ExitKind.INVALID)
        results.append(
            VerificationItem(
                file=artifact_name,
                sha256=artifact.sha256,
                verified=verify_artifact(artifact_path, artifact.sha256),
            )
        )

    result = VerificationResult(
        design_ref=manifest.design_ref,
        platform=f"{manifest.board}/{manifest.runtime}",
        directory=str(target_dir),
        artifacts=results,
        manifest_verified=client is not None,
        checked_ref=checked_ref,
        checked_platform=checked_platform,
        yanked=yanked,
        yanked_reason=yanked_reason,
    )
    return result, manifest
