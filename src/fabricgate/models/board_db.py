"""Board DB model definitions.

Provides normalized lookup of FPGA boards by ``board_id`` or Vivado ``BOARDPART``.
Loads ``official.yaml`` (CLI bundle) and ``custom.yaml`` (user-managed) from
``~/.fabricgate/board-db/``, with custom entries taking precedence.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fabricgate.models.common import FabricGateModel

__all__ = [
    "BoardDb",
    "BoardDbFile",
    "BoardEntry",
    "BoardInterface",
]

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

_EXTRA_IGNORE = ConfigDict(strict=True, frozen=False, extra="ignore")


class BoardInterface(FabricGateModel):
    """Board DB のインターフェースエントリ."""

    model_config = _EXTRA_IGNORE

    type: str
    direction: str | None = None  # "tx" | "rx" | "inout"
    count: int = 1
    source: str = "manual"  # "vivado-boardstore" | "manual" | "community"


class BoardEntry(FabricGateModel):
    """Board DB の1ボードエントリ."""

    model_config = _EXTRA_IGNORE

    board_id: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    display_name: str
    vendor: str | None = None
    boardpart: str | None = None  # Vivado BOARDPART (Vivado 系のみ)
    device: str | None = None  # フルパートナンバー — generic-* では省略
    device_family: str  # e.g. "xczu7ev", "ice40up5k"
    pynq_supported: bool = False
    virtual: bool = False  # True = CLI 生成の仮想ボード
    category: str | None = Field(
        default=None,
        pattern=r"^(generic|custom)$",
    )
    interfaces: list[BoardInterface] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_virtual_rules(self) -> BoardEntry:
        # VIRTUAL_CATEGORY_REQUIRED: virtual=True には category が必須
        if self.virtual and self.category is None:
            raise ValueError("virtual=True のボードには category (generic|custom) が必須です")
        # GENERIC_NO_BOARDPART: generic カテゴリに boardpart は不可
        if self.category == "generic" and self.boardpart is not None:
            raise ValueError("category=generic のボードに boardpart を設定できません")
        return self


# ---------------------------------------------------------------------------
# Internal per-file model
# ---------------------------------------------------------------------------


class BoardDbFile(BaseModel):
    """Single Board DB YAML file (official.yaml or custom.yaml)."""

    model_config = ConfigDict(extra="ignore")

    version: str = Field(
        default="fabricgate-boarddb/v1",
        pattern=r"^fabricgate-boarddb/v1$",
    )
    boards: list[BoardEntry]

    @model_validator(mode="after")
    def _validate_duplicate_board_ids(self) -> BoardDbFile:
        # DUPLICATE_BOARD_ID: 同一ファイル内で board_id の重複を禁止
        seen: set[str] = set()
        for board in self.boards:
            if board.board_id in seen:
                raise ValueError(f"board_id '{board.board_id}' が同一ファイル内で重複しています")
            seen.add(board.board_id)
        return self


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_DEFAULT_OFFICIAL = Path.home() / ".fabricgate" / "board-db" / "official.yaml"
_DEFAULT_CUSTOM = Path.home() / ".fabricgate" / "board-db" / "custom.yaml"


def _parse_bundled_official() -> list[BoardEntry]:
    """Parse the official.yaml bundled with the package.

    Uses ``importlib.resources`` text API so it works correctly in both
    editable-install and zipped-wheel environments.
    """
    ref = importlib.resources.files("fabricgate.data") / "board-db" / "official.yaml"
    text = ref.read_text(encoding="utf-8")
    data: Any = yaml.safe_load(text)
    return BoardDbFile.model_validate(data).boards


def _parse_db_file(path: Path) -> list[BoardEntry]:
    """Parse a Board DB YAML file and return its board entries."""
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BoardDbFile.model_validate(data).boards


# ---------------------------------------------------------------------------
# BoardDb — merged resolver
# ---------------------------------------------------------------------------


class BoardDb:
    """Board DB resolver.

    Loads ``official.yaml`` and ``custom.yaml`` and provides lookup methods.
    Custom entries override official entries with the same ``board_id``.

    Usage::

        db = BoardDb.load()
        entry = db.lookup("zcu104")
        entry = db.lookup_by_boardpart("xilinx.com:zcu104:part0:1.1")
    """

    def __init__(self, boards: list[BoardEntry]) -> None:
        # BOARDPART_UNIQUE: 全体で boardpart の重複を禁止
        seen_boardparts: set[str] = set()
        for board in boards:
            if board.boardpart is not None:
                if board.boardpart in seen_boardparts:
                    raise ValueError(f"boardpart '{board.boardpart}' が Board DB 全体で重複しています")
                seen_boardparts.add(board.boardpart)
        self._boards = boards

    @classmethod
    def load(
        cls,
        official_path: Path | None = None,
        custom_path: Path | None = None,
    ) -> BoardDb:
        """Load the Board DB from official and/or custom YAML files.

        Resolution order for official.yaml:
        1. ``official_path`` if provided explicitly
        2. ``~/.fabricgate/board-db/official.yaml`` if it exists
        3. Bundled ``fabricgate/data/board-db/official.yaml`` (fallback)

        Missing custom.yaml is silently skipped.

        :param official_path: Override path to official.yaml
        :param custom_path: Path to custom.yaml
            (default: ``~/.fabricgate/board-db/custom.yaml``)
        """
        custom_path = custom_path if custom_path is not None else _DEFAULT_CUSTOM

        # Resolve official.yaml: explicit > user dir > bundled
        if official_path is not None:
            official_boards = _parse_db_file(official_path) if official_path.exists() else []
        elif _DEFAULT_OFFICIAL.exists():
            official_boards = _parse_db_file(_DEFAULT_OFFICIAL)
        else:
            official_boards = _parse_bundled_official()

        custom_boards: list[BoardEntry] = []
        if custom_path.exists():
            custom_boards = _parse_db_file(custom_path)

        # custom entries override official entries with the same board_id
        custom_ids = {b.board_id for b in custom_boards}
        merged = list(custom_boards) + [b for b in official_boards if b.board_id not in custom_ids]
        return cls(boards=merged)

    def lookup(self, board_id: str) -> BoardEntry | None:
        """board_id からエントリを検索する."""
        for board in self._boards:
            if board.board_id == board_id:
                return board
        return None

    def lookup_by_boardpart(self, boardpart: str) -> BoardEntry | None:
        """Vivado BOARDPART 属性からエントリを検索する."""
        for board in self._boards:
            if board.boardpart == boardpart:
                return board
        return None

    @property
    def boards(self) -> list[BoardEntry]:
        """全ボードエントリのリスト."""
        return list(self._boards)
