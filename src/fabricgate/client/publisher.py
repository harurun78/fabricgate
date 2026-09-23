"""Push package assembly for `fabricgate push`."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from fabricgate.client.validator import sha256_digest
from fabricgate.models.design_index import DesignIndex
from fabricgate.models.platform_manifest import PlatformManifest, parse_platform_manifest

_PLACEHOLDER_DIGEST = f"sha256:{'a' * 64}"


def _is_placeholder_sha256(sha256: str) -> bool:
    """Return True if *sha256* is a uniform-character placeholder (e.g. all 'a').

    ``fabricgate build`` fills artifact sha256 fields with ``'a' * 64`` because the
    real bitstream hash is not known at manifest-generation time.  Uploading
    such a placeholder to the registry makes ``fabricgate pull --verify`` always fail.
    """
    return len(sha256) == 64 and len(set(sha256)) == 1


class PublishError(Exception):
    """Raised when a push package cannot be assembled."""


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        msg = f"{path} is not a valid YAML mapping"
        raise PublishError(msg)
    return data


def load_design_index(project_dir: Path) -> tuple[DesignIndex, Path]:
    """Find and parse the Design Index in *project_dir*.

    Returns (parsed_index, index_path).
    """
    for candidate in ("fabricgate-index.yaml", "fabricgate-index.yml"):
        p = project_dir / candidate
        if p.exists():
            data = _read_yaml(p)
            return DesignIndex.model_validate(data), p
    msg = f"No fabricgate-index.yaml found in {project_dir}"
    raise PublishError(msg)


def load_platform_manifest(manifest_path: Path) -> PlatformManifest:
    """Parse a platform manifest file."""
    content = manifest_path.read_text(encoding="utf-8")
    return parse_platform_manifest(content)


def collect_artifacts(
    project_dir: Path,
    index: DesignIndex,
    sha_warnings: list[str] | None = None,
    skip_sha_check: bool = False,
    artifact_urls: Mapping[str, str] | None = None,
) -> dict[str, bytes]:
    """Collect all files required for a publish upload.

    Returns a mapping of ``{field_name: content}`` ready for multipart upload.
    Field names match the registry API contract:
    - ``index``                               → the design index YAML
    - ``platform:{pid}:manifest``             → each platform manifest
    - ``platform:{pid}:artifact:{file}``      → artifact files referenced in manifests
    - ``platform:{pid}:artifact-url:{file}``  → the https URL for a file in *artifact_urls*

    *artifact_urls* maps a manifest filename to a public ``https`` URL the registry
    fetches instead of receiving the bytes.  It applies to every platform that
    declares that filename.  A local copy is optional; when present its digest is
    still checked against the manifest.
    """
    files: dict[str, bytes] = {}
    artifact_urls = dict(artifact_urls or {})
    for name, candidate in artifact_urls.items():
        if urlsplit(candidate).scheme != "https":
            msg = f"Artifact URL for {name} must use https: {candidate}"
            raise PublishError(msg)
    unmatched_urls = set(artifact_urls)

    # Include the design index itself
    for candidate in ("fabricgate-index.yaml", "fabricgate-index.yml"):
        p = project_dir / candidate
        if p.exists():
            files["index"] = p.read_bytes()
            break

    for entry in index.platforms:
        platform_key = entry.platform  # e.g. "xc7z020/pynq"
        if str(entry.digest) == _PLACEHOLDER_DIGEST:
            msg = (
                f"Placeholder digest detected for {platform_key}. "
                "Update platform digests before running 'fabricgate push'."
            )
            raise PublishError(msg)

        # Convention: manifest lives at <device>/<runtime>/manifest.yaml
        manifest_rel = f"{platform_key}/manifest.yaml"
        manifest_path = project_dir / manifest_rel
        if not manifest_path.exists():
            msg = f"Manifest not found: {manifest_path}"
            raise PublishError(msg)

        manifest = load_platform_manifest(manifest_path)
        files[f"platform:{platform_key}:manifest"] = manifest_path.read_bytes()

        # Collect artifact files from the manifest
        artifact_dir = manifest_path.parent
        for ref in _extract_artifact_refs(manifest):
            artifact_path = artifact_dir / ref.file
            url = artifact_urls.get(ref.file)
            if url is None and not artifact_path.exists():
                msg = f"Artifact not found: {artifact_path}"
                raise PublishError(msg)
            # Verify digest if declared
            if ref.sha256:
                if _is_placeholder_sha256(ref.sha256):
                    if url is not None:
                        # The registry compares the fetched bytes with this value, so a
                        # placeholder is a guaranteed DIGEST_MISMATCH — fail early.
                        msg = f"Artifact {ref.file} is published by URL but its sha256 is a placeholder"
                        raise PublishError(msg)
                    # Placeholder sha256: skip verification but warn the caller.
                    if not skip_sha_check and sha_warnings is not None:
                        sha_warnings.append(
                            f"Artifact {ref.file} has a placeholder sha256 "
                            "— run with real bitstream to get a verifiable hash"
                        )
                elif artifact_path.exists():
                    actual = sha256_digest(artifact_path)
                    expected = f"sha256:{ref.sha256}"
                    if actual != expected:
                        msg = f"Digest mismatch for {artifact_path}: expected {expected}, got {actual}"
                        raise PublishError(msg)
            if url is not None:
                unmatched_urls.discard(ref.file)
                files[f"platform:{platform_key}:artifact-url:{ref.file}"] = url.encode()
            else:
                files[f"platform:{platform_key}:artifact:{ref.file}"] = artifact_path.read_bytes()

    if unmatched_urls:
        msg = f"Artifact URLs for files not declared in any platform manifest: {', '.join(sorted(unmatched_urls))}"
        raise PublishError(msg)

    return files


def _extract_artifact_refs(manifest: PlatformManifest) -> list[Any]:
    """Extract ArtifactRef objects from any manifest variant."""
    refs: list[Any] = []
    artifacts = getattr(manifest, "artifacts", None)
    if artifacts is None:  # pragma: no cover
        return refs  # pragma: no cover
    # Iterate over all fields of the artifacts model
    for field_name in type(artifacts).model_fields:
        value = getattr(artifacts, field_name, None)
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                if hasattr(item, "file"):
                    refs.append(item)
        elif hasattr(value, "file"):
            refs.append(value)
    return refs
