"""Publish (push) SDK function."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from fabricgate.client import auth
from fabricgate.client.publisher import PublishError, collect_artifacts, load_design_index
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import PushResult
from fabricgate.sdk._helpers import ExitKind, SDKError, _quota_warning_message, _registry_error_kind


def _upload_artifacts_directly(
    client: RegistryClient,
    namespace: str,
    design: str,
    artifact_parts: dict[str, bytes],
) -> None:
    """PUT every artifact part to object storage via presigned URLs.

    ``artifact_parts`` is keyed by multipart field name
    (``platform:{pid}:artifact:{filename}``). Two platforms can ship the same
    filename with different content, and the same content under different
    names, so tickets are matched on ``(filename, sha256)`` — which is also
    what the registry deduplicates on.
    """
    digests: dict[str, tuple[str, str, int]] = {}
    for key, data in artifact_parts.items():
        filename = key.split(":artifact:", 1)[1]
        digests[key] = (filename, hashlib.sha256(data).hexdigest(), len(data))

    requested = {(filename, sha) for filename, sha, _ in digests.values()}
    sizes = {(filename, sha): size for filename, sha, size in digests.values()}
    response = client.create_artifact_uploads(
        namespace,
        design,
        [{"filename": f, "sha256": s, "size": sizes[(f, s)]} for f, s in sorted(requested)],
    )
    tickets = {(ticket.filename, ticket.sha256): ticket for ticket in response.uploads}

    uploaded: set[tuple[str, str]] = set()
    for key, (filename, sha, _size) in digests.items():
        ticket = tickets.get((filename, sha))
        if ticket is None:
            msg = f"Registry issued no upload ticket for {filename}"
            raise SDKError(msg, code=ExitKind.INFRA)
        if ticket.url is None or (filename, sha) in uploaded:
            continue  # already stored, or an identical part under another platform
        client.upload_artifact(ticket, artifact_parts[key])
        uploaded.add((filename, sha))


def push(
    directory: str | Path,
    *,
    namespace: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    token: str | None = None,
    board_override: str | None = None,
    skip_sha_check: bool = False,
    artifact_urls: Mapping[str, str] | None = None,
) -> PushResult:
    """Publish a design to the registry.

    Parameters
    ----------
    directory:
        Path to a directory containing ``fabricgate-index.yaml`` and
        platform subdirectories with manifests and artifacts.
    namespace:
        Override the namespace embedded in the Design Index name.
    registry:
        Base URL for the registry API.
    token:
        Bearer token for authentication.  When *None* the token is loaded
        from the credential store.
    board_override:
        When provided (e.g. ``"generic-xczu7ev"``), replace the ``custom-*``
        board prefix in all platform IDs before publishing.
    artifact_urls:
        ``{filename: https_url}`` for artifacts the registry should fetch from an
        existing public URL instead of receiving an upload.  The manifest still
        declares the file's ``sha256``; the registry verifies the fetched bytes
        against it.

    Returns
    -------
    PushResult
        Published design metadata.
    """
    project_dir = Path(directory)
    try:
        index, _index_path = load_design_index(project_dir)
    except PublishError as exc:
        raise SDKError(str(exc), code=ExitKind.INVALID) from exc
    except Exception as exc:
        if type(exc).__name__ == "ValidationError":
            raise SDKError(f"Invalid design index: {exc}", code=ExitKind.INVALID) from exc
        raise

    # Apply board promotion: replace custom-* prefix with board_override
    if board_override is not None:
        new_entries = []
        for entry in index.platforms:
            platform_id = str(entry.platform)
            if "/" in platform_id:
                old_board, runtime_part = platform_id.split("/", 1)
                if old_board.startswith("custom-"):
                    entry = entry.model_copy(update={"platform": f"{board_override}/{runtime_part}"})
            new_entries.append(entry)
        index = index.model_copy(update={"platforms": new_entries})

    # Parse namespace / design from the index name (e.g. "myns/blink")
    name_parts = str(index.name).split("/", 1)
    if len(name_parts) != 2:
        raise SDKError(f"Invalid design name in index: {index.name}", code=ExitKind.INVALID)
    ns = namespace if namespace is not None else name_parts[0]
    design = name_parts[1]
    version = str(index.version)

    try:
        sha_warnings: list[str] = []
        files = collect_artifacts(
            project_dir,
            index,
            sha_warnings=sha_warnings,
            skip_sha_check=skip_sha_check,
            artifact_urls=artifact_urls,
        )
    except PublishError as exc:
        raise SDKError(str(exc), code=ExitKind.INVALID) from exc

    # Resolve auth token
    effective_token = token
    if effective_token is None:
        creds = auth.load_credentials(registry)
        if creds is not None:
            effective_token = creds.token

    if effective_token is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    # Artifacts go straight to object storage; only metadata travels through
    # the API. Cloud Run caps a request at 32MiB while an artifact may be
    # 256MB, so the bytes cannot go through the registry at all.
    artifact_parts = {key: data for key, data in files.items() if ":artifact:" in key}
    metadata_files = {key: data for key, data in files.items() if key not in artifact_parts}

    try:
        with RegistryClient(base_url=registry, token=effective_token) as client:
            if artifact_parts:
                _upload_artifacts_directly(client, ns, design, artifact_parts)
            response = client.publish_version(ns, design, version, metadata_files)
            quota_warning: str | None = None
            try:
                quota_response = client.get_namespace_quota(ns)
                quota_warning = _quota_warning_message(quota_response)
            except RegistryError:
                # The post-publish quota fetch is best-effort: a failed quota
                # lookup (including a transport NetworkError) must not turn a
                # successful publish into a command failure — just omit the warning.
                quota_warning = None
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return PushResult(
        name=response.name,
        version=response.version,
        platforms=response.platforms,
        published_at=response.published_at,
        quota_warning=quota_warning,
        sha_warning=("; ".join(sha_warnings) if sha_warnings else None),
    )
