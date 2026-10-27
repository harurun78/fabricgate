"""Pull (download) SDK function plus local digest verification."""

from __future__ import annotations

from collections.abc import Callable
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
from fabricgate.models.platform_manifest import parse_platform_manifest
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


def verify(directory: str | Path) -> VerificationResult:
    """Verify artifact digests in a pulled design directory."""
    target_dir = Path(directory)
    manifest_path = _find_manifest_path(target_dir)
    try:
        manifest = parse_platform_manifest(manifest_path.read_text(encoding="utf-8"))
    except (ValidationError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SDKError(f"Invalid manifest {manifest_path}: {exc}", code=ExitKind.INVALID) from exc
    except OSError as exc:
        raise SDKError(f"Cannot read {manifest_path}: {exc}", code=ExitKind.INFRA) from exc

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
            raise SDKError(f"Artifact not found: {artifact_name}", code=ExitKind.INVALID)
        results.append(
            VerificationItem(
                file=artifact_name,
                sha256=artifact.sha256,
                verified=verify_artifact(artifact_path, artifact.sha256),
            )
        )

    return VerificationResult(
        design_ref=manifest.design_ref,
        platform=f"{manifest.board}/{manifest.runtime}",
        directory=str(target_dir),
        artifacts=results,
    )
