"""SHA-256 digest verification."""

from __future__ import annotations

import hashlib
from pathlib import Path


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
