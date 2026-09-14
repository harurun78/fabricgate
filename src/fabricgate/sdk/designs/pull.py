"""Pull (download) SDK function plus local digest verification."""

from __future__ import annotations

from pathlib import Path

from fabricgate.client import auth, puller
from fabricgate.client.puller import AttestationError, AttestationUnavailableError, IntegrityError
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.client.resolver import ResolutionError
from fabricgate.client.validator import verify_artifact
from fabricgate.models.cli import PullResult, VerificationItem, VerificationResult
from fabricgate.models.platform_manifest import parse_platform_manifest
from fabricgate.sdk._helpers import (
    ExitKind,
    SDKError,
    _extract_artifact_refs,
    _find_manifest_path,
    _parse_design_ref,
    _registry_error_kind,
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
) -> PullResult:
    """Download a platform-specific build of a design."""
    if no_deps and deps_only:
        raise SDKError("--no-deps and --deps-only are mutually exclusive.", code=ExitKind.INVALID)

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
        with RegistryClient(base_url=registry, token=effective_token) as client:
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
            )
    except ResolutionError as exc:
        raise SDKError(str(exc), code=ExitKind.UNRESOLVABLE) from exc
    except AttestationUnavailableError as exc:
        raise SDKError(str(exc), code=ExitKind.INFRA) from exc
    except (IntegrityError, AttestationError) as exc:
        raise SDKError(str(exc), code=ExitKind.INVALID) from exc
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
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
    manifest = parse_platform_manifest(manifest_path.read_text(encoding="utf-8"))

    results: list[VerificationItem] = []
    for artifact in _extract_artifact_refs(manifest):
        # Validate that artifact.file is a safe relative filename (no path traversal).
        artifact_name = str(artifact.file)
        artifact_path_obj = Path(artifact_name)
        if (
            not artifact_name
            or artifact_path_obj.is_absolute()
            or ".." in artifact_path_obj.parts
            or len(artifact_path_obj.parts) != 1
        ):
            raise SDKError(
                f"Invalid artifact filename in manifest: {artifact_name!r}",
                code=ExitKind.INVALID,
            )

        artifact_path = target_dir / artifact_path_obj
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
