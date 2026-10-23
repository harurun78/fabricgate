"""Artifact checks shared by push and pull: SHA-256 digests and manifest filenames."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fabricgate.models.platform_manifest import ArtifactRef, KernelModule, PlatformManifest


def sha256_hex(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_digest(path: Path) -> str:
    """Return ``sha256:<hex>`` content-addressable digest."""
    return f"sha256:{sha256_hex(path)}"


def verify_artifact(path: Path, expected_sha256_hex: str) -> bool:
    """Return ``True`` if *path* matches *expected_sha256_hex*."""
    return sha256_hex(path) == expected_sha256_hex


def verify_digest(path: Path, expected_digest: str) -> bool:
    """Return ``True`` if *path* matches ``sha256:<hex>`` digest."""
    return sha256_digest(path) == expected_digest


def is_single_filename(name: str) -> bool:
    """Return True if *name* is one non-empty path segment (no absolute path, ``..`` or ``/``)."""
    parts = Path(name).parts
    return bool(name) and not Path(name).is_absolute() and ".." not in parts and len(parts) == 1


def artifact_refs(manifest: PlatformManifest) -> list[ArtifactRef | KernelModule]:
    """Return every artifact entry (anything with a ``file``) declared by any manifest variant."""
    refs: list[Any] = []
    artifacts = getattr(manifest, "artifacts", None)
    if artifacts is None:
        return refs
    for field_name in type(artifacts).model_fields:
        value = getattr(artifacts, field_name, None)
        if value is None:
            continue
        if isinstance(value, list):
            refs.extend(item for item in value if hasattr(item, "file"))
        elif hasattr(value, "file"):
            refs.append(value)
    return refs
