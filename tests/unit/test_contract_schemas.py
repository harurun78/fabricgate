"""Conformance tests for the published wire-format JSON Schemas.

Guards that each schema is a valid draft-2020-12 document and faithfully
accepts real fixtures / rejects corrupted ones — so a new-language SDK can
trust the published schema for validation.
"""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "schemas"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _bundled_board_db() -> Any:
    ref = importlib.resources.files("fabricgate.data") / "board-db" / "official.yaml"
    return yaml.safe_load(ref.read_text(encoding="utf-8"))


# --- schema validity ------------------------------------------------------


def test_all_schemas_are_valid_draft_2020_12() -> None:
    for name in (
        "design-index.schema.json",
        "platform-manifest.schema.json",
        "board-db.schema.json",
    ):
        Draft202012Validator.check_schema(_schema(name))


# --- good fixtures are accepted ------------------------------------------


def test_design_index_accepts_sample() -> None:
    Draft202012Validator(_schema("design-index.schema.json")).validate(_yaml(FIXTURES / "sample_index.yaml"))


def test_platform_manifest_accepts_sample() -> None:
    Draft202012Validator(_schema("platform-manifest.schema.json")).validate(_yaml(FIXTURES / "sample_manifest.yaml"))


def test_design_index_accepts_hello_seed() -> None:
    """fabricgate/hello seed manifest passes the published wire schema (spec 2026-07-03 §5)."""
    Draft202012Validator(_schema("design-index.schema.json")).validate(_yaml(FIXTURES / "hello_design_index.yaml"))


def test_platform_manifest_accepts_hello_seed() -> None:
    """fabricgate/hello seed platform manifest passes the published wire schema (spec 2026-07-03 §5)."""
    Draft202012Validator(_schema("platform-manifest.schema.json")).validate(
        _yaml(FIXTURES / "hello_platform_manifest.yaml")
    )


def test_design_index_accepts_reference_shell_pair() -> None:
    """reference shell pair indexes pass the published wire schema (spec 2026-07-03 reference-shell §1/§8)."""
    validator = Draft202012Validator(_schema("design-index.schema.json"))
    validator.validate(_yaml(FIXTURES / "pynq_z2_shell_design_index.yaml"))
    validator.validate(_yaml(FIXTURES / "demo_adder_design_index.yaml"))


def test_platform_manifest_accepts_reference_shell_pair() -> None:
    """reference shell pair manifests (shell + partial with ADR-009 pin) pass the published wire schema."""
    validator = Draft202012Validator(_schema("platform-manifest.schema.json"))
    validator.validate(_yaml(FIXTURES / "pynq_z2_shell_platform_manifest.yaml"))
    validator.validate(_yaml(FIXTURES / "demo_adder_platform_manifest.yaml"))


def test_board_db_accepts_bundled_official() -> None:
    Draft202012Validator(_schema("board-db.schema.json")).validate(_bundled_board_db())


@pytest.mark.parametrize(
    ("board_id", "boardpart", "device", "device_family"),
    [
        ("zcu104", "xilinx.com:zcu104:part0:1.1", "xczu7ev-ffvc1156-2-e", "xczu7ev"),
        ("pynq-z2", "tul.com.tw:pynq-z2:part0:1.0", "xc7z020clg400-1", "xc7z020"),
        ("pynq-z1", "www.digilentinc.com:pynq-z1:part0:1.0", "xc7z020clg400-1", "xc7z020"),
        ("zcu111", "xilinx.com:zcu111:part0:1.4", "xczu28dr-ffvg1517-2-e", "xczu28dr"),
        ("rfsoc2x2", "xilinx.com:rfsoc2x2:part0:1.1", "xczu28dr-ffvg1517-2-e", "xczu28dr"),
        ("rfsoc4x2", "realdigital.org:rfsoc4x2:part0:1.0", "xczu48dr-ffvg1517-2-e", "xczu48dr"),
    ],
)
def test_bundled_official_pynq_boards_resolve_both_ways(
    board_id: str, boardpart: str, device: str, device_family: str
) -> None:
    """Every PYNQ board ships with a unique boardpart so `.hwh` reverse lookup and
    `pull --platform {board_id}/pynq` agree on the same entry."""
    from fabricgate.models.board_db import BoardDb, BoardDbFile

    db = BoardDb(BoardDbFile.model_validate(_bundled_board_db()).boards)  # raises on duplicate boardpart
    entry = db.lookup(board_id)
    assert entry is not None
    assert entry.pynq_supported is True
    assert entry.device == device
    assert entry.device_family == device_family
    assert db.lookup_by_boardpart(boardpart) is entry


# --- corrupted fixtures are rejected -------------------------------------


def test_design_index_rejects_bad_version() -> None:
    data = _yaml(FIXTURES / "sample_index.yaml")
    data["version"] = "not-semver"
    errors = list(Draft202012Validator(_schema("design-index.schema.json")).iter_errors(data))
    assert errors


def test_platform_manifest_rejects_unknown_runtime() -> None:
    data = _yaml(FIXTURES / "sample_manifest.yaml")
    data["runtime"] = "no-such-runtime"
    errors = list(Draft202012Validator(_schema("platform-manifest.schema.json")).iter_errors(data))
    assert errors


def test_board_db_rejects_bad_board_id() -> None:
    data = _bundled_board_db()
    data["boards"][0]["board_id"] = "Bad_ID"  # uppercase/underscore violate the pattern
    errors = list(Draft202012Validator(_schema("board-db.schema.json")).iter_errors(data))
    assert errors
