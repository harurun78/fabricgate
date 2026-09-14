"""Platform resolution logic.

Given a :class:`DesignIndex` and an optional platform filter, select the
matching :class:`PlatformEntry`.

Resolution is two-stage (spec: docs/specs/client-behavior.md §6):

1. Exact match (highest priority, unchanged behaviour).
2. Family fallback (only on miss): look up ``board_id -> device_family`` in
   the board DB and retry with ``generic-{device_family}/{runtime}``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from fabricgate.models.design_index import DesignIndex, PlatformEntry

if TYPE_CHECKING:
    from fabricgate.models.board_db import BoardDb


class ResolutionError(Exception):
    """Raised when platform resolution fails."""


class PlatformResolution(NamedTuple):
    """Resolution result with fallback provenance (spec 2026-07-03 §4)."""

    entry: PlatformEntry
    fallback_from: str | None


def resolve_platform_detailed(
    index: DesignIndex,
    platform: str | None = None,
    board_db: BoardDb | None = None,
) -> PlatformResolution:
    """Two-stage resolution: exact match first, then generic-{family} fallback.

    If *platform* is ``None`` and the index has exactly one entry, that
    entry is returned.  Otherwise *platform* must match one entry's
    ``platform`` field exactly, or — on miss — a ``generic-{device_family}``
    entry for the same runtime is selected using the board DB
    (:class:`~fabricgate.models.board_db.BoardDb`).  ``fallback_from`` carries
    the originally requested platform when the fallback stage was used.
    """
    if platform is None:
        if len(index.platforms) == 1:
            return PlatformResolution(index.platforms[0], None)
        available = ", ".join(e.platform for e in index.platforms)
        raise ResolutionError(f"Multiple platforms available ({available}); specify --platform")

    for entry in index.platforms:
        if entry.platform == platform:
            return PlatformResolution(entry, None)

    # Family fallback: board_id/runtime -> generic-{device_family}/runtime
    if "/" in platform:
        board_id, runtime = platform.split("/", 1)
        if not board_id.startswith("generic-"):
            import yaml

            from fabricgate.models.board_db import BoardDb

            try:
                db = board_db if board_db is not None else BoardDb.load()
                board = db.lookup(board_id)
            except (OSError, ValueError, yaml.YAMLError):
                # fallback は加算的: board-db 破損で従来エラー経路を壊さない。
                # 捕捉するのは BoardDb.load() の破損系のみ —
                #   OSError: YAML 読み込み失敗 / yaml.YAMLError: 不正 YAML /
                #   ValueError: schema 不一致 (pydantic ValidationError を含む) と
                #   boardpart 重複 (BoardDb.__init__)。
                # プログラミングエラー (AttributeError/TypeError 等) は透過させる。
                board = None
            if board is not None:
                generic_platform = f"generic-{board.device_family}/{runtime}"
                for entry in index.platforms:
                    if entry.platform == generic_platform:
                        return PlatformResolution(entry, platform)

    available = ", ".join(e.platform for e in index.platforms)
    raise ResolutionError(f"Platform '{platform}' not found. Available: {available}")


def resolve_platform(
    index: DesignIndex,
    platform: str | None = None,
    board_db: BoardDb | None = None,
) -> PlatformEntry:
    """Select a single platform from *index* (exact match, then family fallback)."""
    return resolve_platform_detailed(index, platform, board_db).entry
