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
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from fabricgate.client import cache
from fabricgate.client.registry_client import RegistryClientProtocol, RegistryError
from fabricgate.client.resolver import resolve_platform_detailed, satisfies
from fabricgate.client.validator import artifact_refs, is_single_filename
from fabricgate.models.api.errors import ErrorCode
from fabricgate.models.api.responses import ShellInfo
from fabricgate.models.design_index import DesignIndex, PlatformEntry
from fabricgate.models.platform_manifest import (
    Dependency,
    PlatformManifest,
    ResolvedDependency,
    parse_platform_manifest,
)

ProgressCallback = Callable[[str, int, int | None], None]
"""``on_progress(label, bytes_received, total_bytes)``; *label* is ``"<ns>/<design>:<version> <file>"``."""


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
    yanked_warning: str | None = None
    shell_yanked_warning: str | None = None
    dependency_yanked_warnings: list[str] = field(default_factory=list)
    fallback_from: str | None = None
    """Originally requested platform when generic family fallback was used."""


def _version_detail_to_index(data: dict[str, Any]) -> DesignIndex:
    # ApiPlatformEntry adds API-only fields (artifacts, attestation, ...) that the
    # strict PlatformEntry rejects. Keep only PlatformEntry's own fields so a field
    # added to the API model later does not make pull fail.
    if "platforms" in data:
        data["platforms"] = [{k: v for k, v in p.items() if k in PlatformEntry.model_fields} for p in data["platforms"]]
    # Only what pull uses: a summary, tags or links the current schema would reject (e.g. versions
    # published before #47 with non-http(s) links) must not make pull fail.
    return DesignIndex.model_validate({k: data[k] for k in ("schema", "name", "version", "platforms") if k in data})


def _validate_artifact_filename(artifact_name: str, *, context: str) -> Path:
    """Return the safe single-segment path for *artifact_name* or raise.

    Rejects empty, absolute, traversal, or multi-segment names.
    """
    if not is_single_filename(artifact_name):
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


@dataclass(frozen=True)
class _FetchedManifest:
    """A platform manifest that is on disk (and attested, with a signer), its artifacts not yet fetched."""

    ref: str
    dest: Path
    manifest: PlatformManifest
    fetch: Callable[..., bytes]
    kind: str


def _fetch_manifest(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    board: str,
    runtime: str,
    dest: Path,
    *,
    signer: AttestationSigner | None,
    kind: str = "",
) -> _FetchedManifest:
    """Fetch one platform's manifest into *dest* and, with *signer*, check its attestation.

    *kind* (``""``, ``"dependency"`` or ``"shell"``) only prefixes error messages.
    The manifest is parsed before it is written, so a broken one leaves nothing on disk.
    """
    prefix = f"{kind} " if kind else ""
    ref = f"{namespace}/{design}:{version}"
    manifest_bytes = client.get_platform_manifest_bytes(namespace, design, version, board, runtime)
    manifest = parse_platform_manifest(manifest_bytes.decode("utf-8"))
    for artifact in artifact_refs(manifest):
        # Before anything is written or fetched, so a manifest naming a path outside dest stops the pull here.
        _validate_artifact_filename(str(artifact.file), context=f"{prefix}manifest")
    (dest / "manifest.yaml").write_bytes(manifest_bytes)
    fetch = partial(client.download_artifact, namespace, design, version, board, runtime)
    if signer is not None:
        _verify_manifest_attestation(
            dest,
            manifest,
            fetch,
            signer,
            label=f"{prefix}manifest {ref}",
            expected_ref=ref,
            expected_runtime=runtime,
        )
    return _FetchedManifest(ref, dest, manifest, fetch, kind)


def _download_artifacts(
    fetched: _FetchedManifest,
    *,
    verify_digests: bool,
    cache_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[str], bool]:
    """Download the artifacts *fetched*'s manifest lists into its directory.

    Returns the artifact names and whether every artifact came from the cache.
    With *cache_dir*, an artifact whose pinned sha256 is cached is copied from
    there instead of downloaded, and a downloaded one is added to the cache.
    *on_progress* is told about each artifact; a cached one is reported once, as complete.
    """
    kind = fetched.kind
    prefix = f"{kind} " if kind else ""
    names: list[str] = []
    all_cached = True
    for artifact in artifact_refs(fetched.manifest):
        name = str(artifact.file)
        path = _validate_artifact_filename(name, context=f"{prefix}manifest")
        data = cache.get_blob(cache_dir, artifact.sha256) if cache_dir is not None else None
        downloaded = data is None
        label = f"{fetched.ref} {name}"
        if data is None:
            all_cached = False
            # on_progress is only passed when set, so clients written before it keep working.
            data = (
                fetched.fetch(name)
                if on_progress is None
                else fetched.fetch(name, on_progress=partial(on_progress, label))
            )
        elif on_progress is not None:
            on_progress(label, len(data), len(data))
        _write_verified(
            fetched.dest / path,
            data,
            artifact.sha256,
            verify=verify_digests,
            label=f"{prefix}artifact {name}" if kind else name,
        )
        if downloaded and cache_dir is not None:
            cache.put_blob(cache_dir, data)
        names.append(name)
    return names, bool(names) and all_cached


def _fetch_dependencies(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    device: str,
    runtime: str,
    target_dir: Path,
    *,
    include_optional: bool = False,
    signer: AttestationSigner | None = None,
) -> list[tuple[ResolvedDependency, _FetchedManifest]]:
    """Resolve the dependencies and fetch each one's manifest into ``deps/<ns>/<design>/<version>/``.

    Their artifacts are downloaded later, once every manifest has been checked.
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
        if exc.status_code == 404:
            # No dependencies endpoint or no deps — not an error
            return []
        raise

    fetched: list[tuple[ResolvedDependency, _FetchedManifest]] = []
    # Dependencies come in topological order from server
    for dep in deps_resp.dependencies:
        dep_ns, dep_design = str(dep.name).split("/", 1)
        dep_version = str(dep.resolved_version)
        dep_device, dep_runtime = str(dep.platform).split("/", 1)

        # One path segment per part: joining them with "-" made a-b/c and a/b-c collide.
        dep_dir = target_dir / "deps" / dep_ns / dep_design / dep_version
        dep_dir.mkdir(parents=True, exist_ok=True)

        manifest = _fetch_manifest(
            client,
            dep_ns,
            dep_design,
            dep_version,
            dep_device,
            dep_runtime,
            dep_dir,
            signer=signer,
            kind="dependency",
        )
        fetched.append((dep, manifest))
    return fetched


def _dependency_yanked_warnings(deps: list[tuple[ResolvedDependency, _FetchedManifest]]) -> list[str]:
    """A warning for each dependency that is yanked (an exact constraint still resolves to one, like `verify` says)."""
    warnings: list[str] = []
    for dep, fetched in deps:
        if dep.yanked:
            reason = f": {dep.yanked_reason}" if dep.yanked_reason else ""
            warnings.append(f"Dependency {fetched.ref} is yanked{reason}")
    return warnings


def _fetch_shell(
    client: RegistryClientProtocol,
    namespace: str,
    design: str,
    version: str,
    device: str,
    runtime: str,
    target_dir: Path,
    *,
    signer: AttestationSigner | None = None,
) -> tuple[ShellInfo, _FetchedManifest] | None:
    """Fetch the manifest of the static shell for a partial bitstream, if there is one.

    Returns the registry's shell info and the fetched manifest, or None. Its artifacts
    are downloaded later, once every manifest has been checked.
    """
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

    shell_ns, shell_design = str(shell_info.name).split("/", 1)
    shell_dir = target_dir / "shell" / shell_ns / shell_design / str(shell_info.version)
    shell_dir.mkdir(parents=True, exist_ok=True)

    # The shell may be published for a different board ID than the design, so use
    # shell_info.board, not the design's device.
    manifest = _fetch_manifest(
        client,
        shell_ns,
        shell_design,
        str(shell_info.version),
        shell_info.board,
        shell_info.runtime,
        shell_dir,
        signer=signer,
        kind="shell",
    )
    return shell_info, manifest


def _check_signed_declarations(
    root: PlatformManifest,
    root_platform: str,
    deps: list[tuple[ResolvedDependency, _FetchedManifest]] | None,
    shell: tuple[ShellInfo, _FetchedManifest] | None,
    *,
    check_shell: bool,
) -> None:
    """Check that the registry's dependencies and shell are the ones the signed manifests declare.

    With ``--verify-attestation`` each manifest is signed, but which dependencies and
    shell to pull comes from the registry. Without this check the registry could hand
    over any other manifest from the same signer (an older version, another design).
    *deps* is None when dependencies were not resolved (``--no-deps``); *check_shell*
    is False when the shell was not looked up (``--no-shell``, ``--deps-only``).
    Raises :class:`AttestationError` before any of their artifacts is downloaded.
    """
    if deps is not None:
        _check_dependencies(root, root_platform, deps)
    if not check_shell:
        return
    pin = root.shell_dependency
    if pin is None:
        if shell is not None:
            raise AttestationError(
                f"The registry returned shell {shell[1].ref}, but the signed manifest {root.design_ref} pins no shell."
            )
        return
    pinned_ref = f"{pin.name}:{pin.version.removeprefix('=')}"
    if shell is None:
        raise AttestationError(
            f"The signed manifest {root.design_ref} pins shell {pinned_ref}, but the registry returned no shell."
        )
    shell_info, fetched = shell
    if fetched.ref != pinned_ref:
        raise AttestationError(
            f"The signed manifest {root.design_ref} pins shell {pinned_ref}, but the registry returned {fetched.ref}."
        )
    if not any(artifact.sha256 == pin.sha256 for artifact in artifact_refs(fetched.manifest)):
        # Another genuine platform of the same shell version would pass the ref check.
        raise AttestationError(
            f"Shell {pinned_ref} ({shell_info.board}/{shell_info.runtime}) has no artifact with the sha256 "
            f"that {root.design_ref} pins."
        )


def _check_dependencies(
    root: PlatformManifest, root_platform: str, deps: list[tuple[ResolvedDependency, _FetchedManifest]]
) -> None:
    """Accept only dependencies that a signed manifest reachable from the root declares, and require every declared one.

    The registry's order and ``required_by`` are not trusted: starting from the root's
    declarations, a dependency is accepted when an accepted manifest declares its name with a
    constraint its version satisfies and the platform it was served for, and then its own
    declarations count too. A declaration without ``platform`` means the root's platform, as
    the registry resolves it (not the declaring manifest's). The registry resolves one version
    per design, so a name that comes twice is rejected.
    """
    names = [str(dep.name) for dep, _ in deps]
    if duplicates := sorted({name for name in names if names.count(name) > 1}):
        raise AttestationError(f"The registry returned more than one version of {', '.join(duplicates)}.")

    def declares(d: Dependency, dep: ResolvedDependency) -> bool:
        platform = str(d.platform) if d.platform is not None else root_platform
        return (
            str(d.name) == str(dep.name)
            and str(dep.platform) == platform
            and _satisfies(str(dep.resolved_version), d.version)
        )

    declared = list(root.dependencies)
    pending = list(deps)
    accepted: dict[str, str] = {}
    progress = True
    while pending and progress:
        progress = False
        for item in list(pending):
            dep = item[0]
            if any(declares(d, dep) for d in declared):
                pending.remove(item)
                accepted[str(dep.name)] = str(dep.resolved_version)
                declared.extend(item[1].manifest.dependencies)
                progress = True
    if pending:
        refs = ", ".join(f"{fetched.ref} ({dep.platform})" for dep, fetched in pending)
        raise AttestationError(f"The registry returned dependencies that no signed manifest declares: {refs}")
    for d in declared:
        version = accepted.get(str(d.name))
        if version is None:
            if not d.optional:
                raise AttestationError(
                    f"A signed manifest needs {d.name} {d.version}, but the registry did not return it."
                )
        elif not _satisfies(version, d.version):
            raise AttestationError(
                f"A signed manifest needs {d.name} {d.version}, but the registry returned {version}."
            )


def _satisfies(version: str, constraint: str) -> bool:
    try:
        return satisfies(version, constraint)
    except ValueError as exc:
        raise AttestationError(str(exc)) from exc


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
    on_progress: ProgressCallback | None = None,
) -> PullOutcome:
    """Download a platform-specific build of a design and its dependencies.

    With *verify_attestation*, every manifest (root, dependencies, shell) must
    carry a cosign bundle signed by *attestation_signer*. *on_progress* is
    called while root, dependency and shell artifacts are fetched.

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
    cache_path = Path(cache_dir) if cache_dir is not None else None
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

    # The registry still serves a yanked version by its exact ref; say so like `verify` does.
    yanked_warning: str | None = None
    if version_detail.yanked:
        reason = f": {version_detail.yanked_reason}" if version_detail.yanked_reason else ""
        yanked_warning = f"{version_detail.name}:{version_detail.version} is yanked{reason}"

    index = _version_detail_to_index(version_detail.model_dump(by_alias=True))
    resolution = resolve_platform_detailed(index, platform)
    selected = resolution.entry
    board_id, runtime = selected.platform.split("/", 1)

    target_dir = Path(output) if output is not None else Path.cwd() / f"{design}-{version}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Every manifest (root, dependencies, shell) is fetched and checked before any artifact is
    # downloaded, so with --verify-attestation nothing the signed manifests do not declare is written.
    root: _FetchedManifest | None = None
    root_manifest: PlatformManifest | None = None
    if not deps_only:
        root = _fetch_manifest(client, namespace, design, version, board_id, runtime, target_dir, signer=signer)
        root_manifest = root.manifest
    elif signer is not None:
        # --deps-only skips the root, but its signed manifest says which dependencies are expected.
        with tempfile.TemporaryDirectory() as scratch:
            root_manifest = _fetch_manifest(
                client, namespace, design, version, board_id, runtime, Path(scratch), signer=signer
            ).manifest

    deps = (
        None
        if no_deps
        else _fetch_dependencies(
            client,
            namespace,
            design,
            version,
            board_id,
            runtime,
            target_dir,
            include_optional=include_optional_deps,
            signer=signer,
        )
    )
    check_shell = not deps_only and not no_shell
    shell = (
        _fetch_shell(client, namespace, design, version, board_id, runtime, target_dir, signer=signer)
        if check_shell
        else None
    )
    if signer is not None and root_manifest is not None:
        _check_signed_declarations(root_manifest, f"{board_id}/{runtime}", deps, shell, check_shell=check_shell)

    download = partial(
        _download_artifacts, verify_digests=verify_digests, cache_dir=cache_path, on_progress=on_progress
    )
    downloaded_files: list[str] = []
    cached = False
    if root is not None:
        downloaded_files, cached = download(root)
    dep_refs: list[str] = []
    dependency_yanked_warnings: list[str] = []
    if deps:
        for _, fetched in deps:
            download(fetched)
        dep_refs = [fetched.ref for _, fetched in deps]
        dependency_yanked_warnings = _dependency_yanked_warnings(deps)
    shell_ref: str | None = None
    shell_yanked_warning: str | None = None
    if shell is not None:
        shell_info, shell_manifest = shell
        download(shell_manifest)
        shell_ref = shell_manifest.ref
        # The pin is an exact version, so a yanked shell still resolves; say so like `verify` does.
        if shell_info.yanked:
            reason = f": {shell_info.yanked_reason}" if shell_info.yanked_reason else ""
            shell_yanked_warning = f"Shell {shell_ref} is yanked{reason}"

    if cache_path is not None and not deps_only:
        cache.store(
            version_detail.name,
            version_detail.version,
            selected.platform,
            selected.digest,
            target_dir,
            cache_path,
        )

    return PullOutcome(
        name=version_detail.name,
        version=version_detail.version,
        platform=selected.platform,
        path=str(target_dir),
        artifacts=downloaded_files,
        cached=cached,
        dependencies=dep_refs,
        shell=shell_ref,
        deprecated_warning=deprecated_warning,
        yanked_warning=yanked_warning,
        shell_yanked_warning=shell_yanked_warning,
        dependency_yanked_warnings=dependency_yanked_warnings,
        fallback_from=resolution.fallback_from,
    )
