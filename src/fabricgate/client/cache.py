"""Local cache manager.

Cache layout::

    ~/.fabricgate/cache/
    ├── index.json          # CacheIndex
    └── <namespace>/<design>/<version>/<device>/<runtime>/
        ├── manifest.yaml
        └── <artifact files>
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fabricgate.models.cli import CacheEntry, CacheIndex

_DEFAULT_CACHE_DIR = Path.home() / ".fabricgate" / "cache"


def _index_path(cache_dir: Path) -> Path:
    return cache_dir / "index.json"


def load_index(cache_dir: Path | None = None) -> CacheIndex:
    """Load or initialise the cache index."""
    p = _index_path(cache_dir or _DEFAULT_CACHE_DIR)
    if p.exists():
        return CacheIndex.model_validate_json(p.read_bytes())
    return CacheIndex()


def save_index(index: CacheIndex, cache_dir: Path | None = None) -> None:
    """Persist the cache index."""
    p = _index_path(cache_dir or _DEFAULT_CACHE_DIR)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(index.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


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
