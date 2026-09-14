"""Fixture factory — realistic-size fake FPGA binary files using os.urandom.

Phase A of OPS-FIXTURE-001: provides deterministic-size helpers for unit
and integration tests that need actual binary payloads (e.g. Upload UI,
artifact storage, SHA-256 verification).

Usage::

    from tests.fixtures import make_bitstream, write_fixture_file

    data = make_bitstream()           # 1 MiB random bytes
    path = write_fixture_file(tmp_path, "top.bit")  # writes to disk
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Realistic default sizes (bytes) for common FPGA artifact types
_BITSTREAM_SIZE = 1 * 1024 * 1024  # 1 MiB  — typical partial bitstream
_OVERLAY_SIZE = 8 * 1024 * 1024  # 8 MiB  — typical full overlay


def make_bitstream(size: int = _BITSTREAM_SIZE) -> bytes:
    """Return *size* random bytes representing a fake bitstream file."""
    return os.urandom(size)


def make_overlay(size: int = _OVERLAY_SIZE) -> bytes:
    """Return *size* random bytes representing a fake PYNQ overlay (.bit)."""
    return os.urandom(size)


def sha256_of(data: bytes) -> str:
    """Return the hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def write_fixture_file(
    directory: Path,
    filename: str,
    *,
    size: int = _BITSTREAM_SIZE,
    data: bytes | None = None,
) -> tuple[Path, str]:
    """Write a fake binary file to *directory* and return (path, sha256).

    Args:
        directory: Destination directory (must exist).
        filename: File name to create inside *directory*.
        size: Number of random bytes to generate when *data* is not provided.
        data: Explicit byte content. If provided, *size* is ignored.

    Returns:
        A (Path, sha256_hex) tuple.
    """
    payload = data if data is not None else os.urandom(size)
    digest = sha256_of(payload)
    path = directory / filename
    path.write_bytes(payload)
    return path, digest
