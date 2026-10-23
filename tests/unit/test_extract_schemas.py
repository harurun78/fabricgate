"""Unit tests for the wire-format JSON Schema extractor."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.extract_schemas import build_schemas

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def test_build_schemas_returns_three_contracts() -> None:
    schemas = build_schemas()
    assert set(schemas) == {
        "design-index.schema.json",
        "platform-manifest.schema.json",
        "board-db.schema.json",
    }


def test_design_index_schema_metadata_and_wire_names() -> None:
    schema = build_schemas()["design-index.schema.json"]
    assert schema["$schema"] == DRAFT
    assert schema["$id"] == "urn:fabricgate:schema:design-index:v1"
    assert schema["title"]
    # by_alias=True → wire field name "schema" (not the Python attr "schema_")
    assert "schema" in schema["properties"]
    assert "schema_" not in schema["properties"]
    assert "platforms" in schema["properties"]


def test_platform_manifest_schema_is_discriminated_union() -> None:
    schema = build_schemas()["platform-manifest.schema.json"]
    assert schema["$id"] == "urn:fabricgate:schema:platform-manifest:v1"
    # Discriminated union surfaces as oneOf (+ a discriminator mapping)
    assert "oneOf" in schema or "discriminator" in schema


def test_board_db_schema_has_boards_array() -> None:
    schema = build_schemas()["board-db.schema.json"]
    assert schema["$id"] == "urn:fabricgate:schema:board-db:v1"
    assert schema["properties"]["boards"]["type"] == "array"


def test_main_runs_outside_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.extract_schemas as extract_schemas

    out_dir = tmp_path / "schemas"
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.setattr(extract_schemas, "SCHEMAS_DIR", out_dir)
    monkeypatch.chdir(cwd)

    extract_schemas.main()

    assert {p.name for p in out_dir.iterdir()} == set(build_schemas())
