#!/usr/bin/env python3
"""Extract JSON Schemas for the author-facing wire formats.

Generates machine-readable, versioned JSON Schema (draft 2020-12) for the
file formats that build tools / new-language SDKs author and parse:

    docs/contracts/schemas/design-index.schema.json
    docs/contracts/schemas/platform-manifest.schema.json
    docs/contracts/schemas/board-db.schema.json

These are NOT covered by docs/contracts/openapi.* (which describes the HTTP
API). Schemas are generated from the Pydantic models so they cannot drift;
CI's contract-drift gate regenerates and diffs them.
"""

from __future__ import annotations

import json
from pathlib import Path

from fabricgate.models.board_db import BoardDbFile
from fabricgate.models.design_index import DesignIndex
from fabricgate.models.platform_manifest import _platform_manifest_adapter

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "docs" / "contracts" / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def build_schemas() -> dict[str, dict[str, object]]:
    """Return {filename: json_schema_dict} for the three wire formats.

    All schemas use by_alias=True so they reflect the wire field names
    (e.g. ``schema``) rather than the Python attribute names (``schema_``).
    """
    design_index = DesignIndex.model_json_schema(by_alias=True)
    design_index["$schema"] = DRAFT
    design_index["$id"] = "urn:fabricgate:schema:design-index:v1"
    design_index["title"] = "FabricGate Design Index"
    design_index["description"] = (
        "Top-level descriptor for a versioned FPGA design (fabricgate-index/v1). Lists per-platform builds."
    )

    platform_manifest = _platform_manifest_adapter.json_schema(by_alias=True)
    platform_manifest["$schema"] = DRAFT
    platform_manifest["$id"] = "urn:fabricgate:schema:platform-manifest:v1"
    platform_manifest["title"] = "FabricGate Platform Manifest"
    platform_manifest["description"] = (
        "Per-platform manifest, discriminated by runtime (pynq | linux-fpgamgr | nanopynq)."
    )

    board_db = BoardDbFile.model_json_schema(by_alias=True)
    board_db["$schema"] = DRAFT
    board_db["$id"] = "urn:fabricgate:schema:board-db:v1"
    board_db["title"] = "FabricGate Board DB"
    board_db["description"] = "Board DB file (fabricgate-boarddb/v1): board_id → device/platform metadata."

    return {
        "design-index.schema.json": design_index,
        "platform-manifest.schema.json": platform_manifest,
        "board-db.schema.json": board_db,
    }


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, schema in build_schemas().items():
        path = SCHEMAS_DIR / filename
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
