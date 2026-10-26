"""Local cache manager.

Cache layout::

    ~/.fabricgate/cache/
    ├── index.json          # CacheIndex: what was pulled, and where to (``fabricgate list``)
    └── blobs/sha256/<hex>  # artifact bytes, named by their SHA-256

Artifacts are looked up by the sha256 the platform manifest pins, and a blob
is only used after hashing it again, so a damaged or edited file is dropped
and downloaded instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from fabricgate.models.cli import CacheEntry, CacheIndex

_log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".fabricgate" / "cache"


def _index_path(cache_dir: Path) -> Path:
    return cache_dir / "index.json"


def load_index(cache_dir: Path | None = None) -> CacheIndex:
    """Load or initialise the cache index.

    The index only records what was pulled, so an unreadable one is replaced by
    an empty index (with a warning) instead of failing the command.
    """
    p = _index_path(cache_dir or _DEFAULT_CACHE_DIR)
    if p.exists():
        try:
            return CacheIndex.model_validate_json(p.read_bytes())
        except ValueError as exc:
            _log.warning("ignoring unreadable cache index %s: %s", p, exc)
    return CacheIndex()


def save_index(index: CacheIndex, cache_dir: Path | None = None) -> None:
    """Persist the cache index."""
    p = _index_path(cache_dir or _DEFAULT_CACHE_DIR)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so an interrupted pull never leaves a half-written index.
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(index.model_dump(mode="json"), indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def lookup(
    name: str,
    version: str,
    platform: str,
    cache_dir: Path | None = None,
) -> CacheEntry | None:
    """Return a cache entry if it exists, else ``None``."""
    idx = load_index(cache_dir)
    for entry in idx.entries:
        if entry.name == name and entry.version == version and entry.platform == platform:
            if Path(entry.path).exists():
                return entry
    return None


def store(
    name: str,
    version: str,
    platform: str,
    digest: str,
    artifact_dir: Path,
    cache_dir: Path | None = None,
) -> CacheEntry:
    """Register a downloaded design in the cache index."""
    idx = load_index(cache_dir)

    # Remove stale entry if exists
    idx.entries = [e for e in idx.entries if not (e.name == name and e.version == version and e.platform == platform)]

    entry = CacheEntry(
        name=name,
        version=version,
        platform=platform,
        path=str(artifact_dir),
        pulled_at=datetime.now(UTC),
        digest=digest,
    )
    idx.entries.append(entry)
    save_index(idx, cache_dir)
    return entry


def platform_dir(
    name: str,
    version: str,
    platform: str,
    cache_dir: Path | None = None,
) -> Path:
    """Return the canonical cache directory for a platform build."""
    base = cache_dir or _DEFAULT_CACHE_DIR
    ns, design = name.split("/", 1)
    device, runtime = platform.split("/", 1)
    return base / ns / design / version / device / runtime


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _blob_path(cache_dir: Path, sha256: str) -> Path:
    if not _SHA256_HEX.match(sha256):
        raise ValueError(f"not a sha256 hex digest: {sha256!r}")
    return cache_dir / "blobs" / "sha256" / sha256


def get_blob(cache_dir: Path, sha256: str) -> bytes | None:
    """Return the cached bytes whose SHA-256 is *sha256*, or ``None``.

    The bytes are hashed again before they are returned; a blob that no longer
    matches is removed. Read errors count as a miss: the caller downloads instead.
    """
    path = _blob_path(cache_dir, sha256)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        _log.warning("ignoring unreadable cache blob %s: %s", path, exc)
        return None
    if hashlib.sha256(data).hexdigest() != sha256:
        _log.warning("removing damaged cache blob %s", path)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("could not remove %s: %s", path, exc)
        return None
    return data


def put_blob(cache_dir: Path, data: bytes) -> None:
    """Store *data* under its SHA-256. Write errors are logged, not raised: the pull itself succeeded."""
    path = _blob_path(cache_dir, hashlib.sha256(data).hexdigest())
    if path.exists():
        return
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        _log.warning("could not write cache blob %s: %s", path, exc)
