"""Push package assembly for `fabricgate push`."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from fabricgate.client.validator import artifact_refs, is_single_filename, sha256_digest
from fabricgate.models.design_index import DesignIndex
from fabricgate.models.platform_manifest import PlatformManifest, parse_platform_manifest


def _is_placeholder_sha256(sha256: str) -> bool:
    """Return True if *sha256* is 64 copies of one character, which no real hash is.

    ``fabricgate build`` fills artifact sha256 fields and the index digest with
    ``'a' * 64`` because the real hash is not known at generation time. Any single
    repeated character counts, so hand-written stand-ins such as ``'0' * 64`` are
    caught too. Uploading such a placeholder makes ``fabricgate pull --verify`` always fail.
    """
    return len(sha256) == 64 and len(set(sha256)) == 1


# `fabricgate push` shows its "compute real artifact hashes" tip for warnings that contain this.
PLACEHOLDER_SHA256_WARNING = "has a placeholder sha256"


def _manifest_digest(manifest: bytes) -> str:
    """Return the index ``digest`` of *manifest*.

    The registry rejects a publish whose index digest is not the manifest it receives
    (``400 DIGEST_MISMATCH``), so push computes it instead of trusting the file.
    """
    return f"sha256:{hashlib.sha256(manifest).hexdigest()}"


class PublishError(Exception):
    """Raised when a push package cannot be assembled."""


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        msg = f"{path} is not a valid YAML mapping"
        raise PublishError(msg)
    return data


def _find_index_path(project_dir: Path) -> Path | None:
    for candidate in ("fabricgate-index.yaml", "fabricgate-index.yml"):
        p = project_dir / candidate
        if p.exists():
            return p
    return None


def load_design_index(project_dir: Path) -> tuple[DesignIndex, Path]:
    """Find and parse the Design Index in *project_dir*.

    Returns (parsed_index, index_path).
    """
    p = _find_index_path(project_dir)
    if p is None:
        msg = f"No fabricgate-index.yaml found in {project_dir}"
        raise PublishError(msg)
    return DesignIndex.model_validate(_read_yaml(p)), p


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

    # Parsed from the file rather than dumped from *index*, so only the digests change.
    index_path = _find_index_path(project_dir)
    index_data: dict[str, Any] | None = None
    if index_path is not None:
        files["index"] = index_path.read_bytes()
        index_data = yaml.safe_load(files["index"])

    for entry in index.platforms:
        platform_key = entry.platform  # e.g. "xc7z020/pynq"

        # Convention: manifest lives at <board_id>/<runtime>/manifest.yaml
        manifest_rel = f"{platform_key}/manifest.yaml"
        manifest_path = project_dir / manifest_rel
        if not manifest_path.exists():
            msg = f"Manifest not found: {manifest_path}"
            raise PublishError(msg)

        manifest = load_platform_manifest(manifest_path)
        manifest_bytes = manifest_path.read_bytes()
        files[f"platform:{platform_key}:manifest"] = manifest_bytes

        # `fabricgate build` writes a placeholder digest; anything else that differs was written by hand.
        digest = _manifest_digest(manifest_bytes)
        declared = str(entry.digest)
        if declared != digest and not _is_placeholder_sha256(declared.removeprefix("sha256:")):
            if sha_warnings is not None:
                sha_warnings.append(
                    f"Index digest for {platform_key} does not match {manifest_rel}; push sends the manifest's digest"
                )
        if index_data is not None:
            for raw in index_data["platforms"]:
                if raw["platform"] == platform_key:
                    raw["digest"] = digest

        # Collect artifact files from the manifest
        artifact_dir = manifest_path.parent
        for ref in artifact_refs(manifest):
            # Checked before any read: a name that escapes the manifest directory
            # would otherwise upload an arbitrary local file.
            if not is_single_filename(ref.file):
                msg = f"Invalid artifact filename in {manifest_rel}: {ref.file!r}"
                raise PublishError(msg)
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
                            f"Artifact {ref.file} {PLACEHOLDER_SHA256_WARNING} "
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

        # The cosign bundle signs manifest.yaml, so the manifest cannot pin it by sha256
        # and it cannot use the direct upload; it travels as its own inline part and the
        # registry serves it from artifacts/{bundle}.
        if manifest.attestation is not None:
            bundle = manifest.attestation.bundle
            if not is_single_filename(bundle):
                msg = f"Invalid attestation bundle filename in {manifest_rel}: {bundle!r}"
                raise PublishError(msg)
            bundle_path = artifact_dir / bundle
            if bundle_path.is_file():
                files[f"platform:{platform_key}:attestation:{bundle}"] = bundle_path.read_bytes()
            elif sha_warnings is not None:
                # Earlier clients never uploaded the bundle, so a missing file stays a warning.
                sha_warnings.append(
                    f"Attestation bundle {bundle} not found next to {manifest_rel}; "
                    "pull --verify-attestation will fail for this platform"
                )

    if unmatched_urls:
        msg = f"Artifact URLs for files not declared in any platform manifest: {', '.join(sorted(unmatched_urls))}"
        raise PublishError(msg)

    if index_data is not None:
        files["index"] = yaml.safe_dump(index_data, sort_keys=False).encode()
    return files


def promote_platforms(files: Mapping[str, bytes], promotions: Mapping[str, str]) -> dict[str, bytes]:
    """Rename platforms in the parts built by :func:`collect_artifacts`.

    *promotions* maps an old platform ID to the new one (e.g.
    ``"custom-xczu7ev-ffvc1156/pynq"`` → ``"generic-xczu7ev/pynq"``). The part
    keys, the manifest ``board`` and the index entry (platform and digest) all
    move together, so the registry sees one consistent platform. The files on
    disk are not touched.

    A manifest with an attestation cannot be promoted: rewriting ``board``
    changes the bytes its signature covers.
    """
    index = yaml.safe_load(files["index"])
    targets = list(promotions.values())
    kept = {entry["platform"] for entry in index["platforms"]} - set(promotions)
    clash = sorted({t for t in targets if targets.count(t) > 1} | (set(targets) & kept))
    if clash:
        # Two parts under one platform key would silently overwrite each other.
        msg = f"Cannot promote: more than one platform would become {', '.join(clash)}"
        raise PublishError(msg)
    promoted: dict[str, bytes] = {}
    for key, data in files.items():
        if key == "index" or not key.startswith("platform:"):
            promoted[key] = data
            continue
        # Platform IDs contain "/" but never ":", so the first ":" ends the ID.
        platform_id, part = key.removeprefix("platform:").split(":", 1)
        new_id = promotions.get(platform_id)
        if new_id is None:
            promoted[key] = data
            continue
        if part == "manifest":
            manifest = yaml.safe_load(data)
            if manifest.get("attestation"):
                msg = (
                    f"Cannot promote {platform_id}: its manifest is signed (attestation) and promotion "
                    "rewrites it. Promote before signing, or push without promotion."
                )
                raise PublishError(msg)
            manifest["board"] = new_id.split("/", 1)[0]
            data = yaml.safe_dump(manifest, sort_keys=False).encode()
            for entry in index["platforms"]:
                if entry["platform"] == platform_id:
                    entry["platform"] = new_id
                    entry["digest"] = _manifest_digest(data)
        promoted[f"platform:{new_id}:{part}"] = data
    promoted["index"] = yaml.safe_dump(index, sort_keys=False).encode()
    return promoted
