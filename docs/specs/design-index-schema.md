# Design Index Schema

Version: 1.0.0-draft
Date: 2026-03-17
Parent: [README.md](./README.md)

> **Machine-readable schema:** [`docs/contracts/schemas/design-index.schema.json`](../contracts/schemas/design-index.schema.json) (generated SoT; this page is the human explanation).

---

## 1. Purpose

The Design Index is the top-level descriptor for a versioned FPGA design. It lists all available platform-specific builds and provides the metadata needed for platform resolution.

Analogous to an [OCI Image Index](https://github.com/opencontainers/image-spec/blob/main/image-index.md).

## 2. Schema

```yaml
# Required
schema: fabricgate-index/v1    # Fixed schema identifier
name: <namespace>/<design>     # Lowercase, [a-z0-9-]+/[a-z0-9-]+
version: <semver>              # Semantic versioning (X.Y.Z)

# Optional metadata
summary: <string>              # One-line description (max 200 chars)
license: <SPDX-identifier>    # e.g., MIT, Apache-2.0, BSD-3-Clause
author: <string>               # Author or organization name
repository: <url>              # Source repository URL
docs: <url>                    # Documentation URL
tags: [<string>, ...]          # Searchable tags (max 10)

# Required: at least one platform
platforms:
  - platform: <board_id>/<runtime> # Platform ID (Board DB canonical board_id)
    digest: <algo>:<hex>           # Content-addressable digest of Platform Manifest
    size: <int>                    # Total artifact size in bytes (optional)
    speed_grade:                   # Optional: speed grade compatibility
      min: <string>                # Minimum required speed grade
      tested: [<string>, ...]      # Actually tested speed grades
    shell_dependency:              # Optional: partial bitstream only — static shell dependency
      name: <namespace>/<design>
      version: =<X.Y.Z>            # Exact match only
      sha256: <64-hex>             # Optional: shell bitstream hex digest
```

## 3. Field Specifications

### 3.1 `schema`

Fixed value: `fabricgate-index/v1`

Must be the first field. Used for schema detection and forward compatibility.

### 3.2 `name`

Format: `{namespace}/{design}`

```
Regex: ^[a-z0-9]([a-z0-9-]*[a-z0-9])?/[a-z0-9]([a-z0-9-]*[a-z0-9])?$
Max length: 128 characters total
```

- `namespace`: Organization or user (e.g., `xilinx`, `univ-tokyo`, `community`)
- `design`: Design name (e.g., `axi-dma-demo`, `blink`, `fft-accelerator`)

### 3.3 `version`

Semantic versioning: `MAJOR.MINOR.PATCH`

```
Regex: ^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$
```

Pre-release labels (`-alpha`, `-rc.1`) are NOT supported in v1.

### 3.5 `license`

Optional. SPDX license expression.

```
Pattern: ^([A-Za-z0-9\-.+]+)(\s+(AND|OR|WITH)\s+[A-Za-z0-9\-.+]+)*$
Max length: 512 characters
```

Examples of valid values:

| Value | Notes |
|---|---|
| `MIT` | Single SPDX identifier |
| `Apache-2.0` | Single SPDX identifier |
| `GPL-2.0-only` | Version-qualified identifier |
| `MIT AND Apache-2.0` | Compound expression (components under different licenses) |
| `MIT OR GPL-2.0-only` | User choice expression |
| `GPL-2.0-only WITH Classpath-exception-2.0` | Exception expression |
| `LicenseRef-custom` | User-defined license reference |

> **Note:** The registry validates the **format** of the expression (regex match) but does NOT enforce that the identifier exists in the SPDX license list. Non-standard identifiers are accepted with a `WARNING` in server logs.

### 3.4 `platforms[]`

At least one entry required.

#### `platform`

Format: `{board_id}/{runtime}`

```
board_id: ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$
runtime:  ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$
```

`board_id` は FabricGate Board DB のカノニカル識別子（小文字）。CLI が HWH の `BOARDPART` 属性を Board DB で引き当てて自動解決する。

**仮想 board_id**（登録ボードが見つからない場合に CLI が自動生成）：

| 種別 | パターン | 例 | 用途 |
|------|----------|-----|------|
| generic | `generic-{device_family}` | `generic-xczu7ev` | AXI-only デザイン、デバイス互換 |
| custom  | `custom-{device}-{package}` | `custom-xczu7ev-ffvc1156` | 未登録カスタムボード |

`generic-*` は同一 device_family を持つすべてのボードで自動マッチする。`custom-*` は同一 ID の完全一致のみマッチ。

Known board_id values (the bundled `official.yaml`, see `board-db-schema.md`):

| board_id | Board | device |
|----------|-------|--------|
| `zcu104` | ZCU104 | xczu7ev-ffvc1156-2-e |
| `zcu111` | ZCU111 RFSoC | xczu28dr-ffvg1517-2-e |
| `rfsoc2x2` | RFSoC 2x2 | xczu28dr-ffvg1517-2-e |
| `rfsoc4x2` | RFSoC 4x2 | xczu48dr-ffvg1517-2-e |
| `pynq-z2` | PYNQ-Z2 | xc7z020clg400-1 |
| `pynq-z1` | PYNQ-Z1 | xc7z020clg400-1 |
| `pico-ice` | pico-ice | ice40up5k-sg48 |
| `generic-xczu7ev` | (virtual) | xczu7ev（任意パッケージ）|
| `generic-xc7z020` | (virtual) | xc7z020（任意パッケージ）|

Known runtime values: `pynq`, `linux-fpgamgr`, `nanopynq`

Registry MAY reject unknown board_id/runtime values in strict mode, or accept them in permissive mode.

#### `digest`

Content-addressable digest of the Platform Manifest file.

Format: `sha256:<64-hex-chars>`

```
Regex: ^sha256:[0-9a-f]{64}$
```

Used for integrity verification and Platform Manifest retrieval.

#### `speed_grade`

Optional. Declares speed grade compatibility.

- `min`: The speed grade the design was synthesized for. Faster grades (higher absolute number for Xilinx) are compatible.
- `tested`: List of speed grades with confirmed hardware test results.

Xilinx speed grade ordering (slowest → fastest): `-1` < `-2` < `-3`

Compatibility rule: if design targets `min: "-2"`, it runs on `-2` and `-3`, NOT on `-1`.

#### `shell_dependency`

Optional. Declares the static Shell this partial bitstream was built against.
Required when the corresponding Platform Manifest has `bitstream_type: partial`.

| Field | Description |
|-------|-------------|
| `name` | Shell design reference (`namespace/design`) |
| `version` | Exact shell version (`=X.Y.Z`) — no ranges allowed |
| `sha256` | Optional hex digest of the shell bitstream for extra integrity check |

## 4. Examples

### 4.1 Minimal (single platform)

```yaml
schema: fabricgate-index/v1
name: univ-lab/fft-demo
version: 0.1.0
platforms:
  - platform: zcu104/pynq
    digest: sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
```

### 4.1b AXI-only design (generic virtual board)

```yaml
schema: fabricgate-index/v1
name: univ-lab/fft-demo
version: 0.1.0
summary: "FFT demo — AXI-only, device-portable"
platforms:
  - platform: generic-xczu7ev/pynq   # AXI-only: xczu7ev を持つ全ボードで自動マッチ
    digest: sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
    speed_grade:
      min: "-2"
      tested: ["-2"]
```

### 4.2 Multi-platform with metadata

```yaml
schema: fabricgate-index/v1
name: fabricgate/blink
version: 1.0.0
summary: "LED blink reference design — multi-platform demo"
license: Apache-2.0
author: FabricGate Project
repository: https://github.com/fabricgate/blink
tags: [reference, blink, led, getting-started]

platforms:
  - platform: zcu104/pynq
    digest: sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd
    size: 256000
    speed_grade:
      min: "-2"
      tested: ["-2"]

  - platform: zcu104/linux-fpgamgr
    digest: sha256:eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011
    size: 258000
    speed_grade:
      min: "-2"
      tested: ["-2"]

  - platform: pico-ice/nanopynq
    digest: sha256:22334455223344552233445522334455223344552233445522334455223344556
    size: 32000
```

### 4.3 Zynq-7000 dual-runtime

```yaml
schema: fabricgate-index/v1
name: xilinx/axi-dma-demo
version: 2.0.1
summary: "AXI DMA streaming demo with loopback test"
license: MIT
tags: [dma, axi-stream, zynq]

platforms:
  - platform: pynq-z2/pynq
    digest: sha256:11112222111122221111222211112222111122221111222211112222111122223
    speed_grade:
      min: "-1"
      tested: ["-1"]

  - platform: pynq-z2/linux-fpgamgr
    digest: sha256:33334444333344443333444433334444333344443333444433334444333344445
    speed_grade:
      min: "-1"
      tested: ["-1"]
```

## 5. Validation Rules

| Rule | Severity |
|------|----------|
| `schema` must be `fabricgate-index/v1` | Error |
| `name` must match regex | Error |
| `version` must be valid semver | Error |
| `platforms` must have ≥1 entry | Error |
| Each `platform` must match `board_id/runtime` format | Error |
| Each `digest` must be valid sha256 | Error |
| No duplicate `(platform, shell_dependency)` combination within one index | Error |
| `license`, if present, must match SPDX expression pattern (§3.5) | Error |
| `license` empty string is not permitted; use `null` / omit for "no license" | Error |
| `license` identifier not in the published SPDX license list | Warning |
| `summary` max 200 chars | Warning |
| `tags` max 10 items | Warning |
| `speed_grade.tested` should include `speed_grade.min` | Warning |

## 6. Registry Storage

The Design Index is stored in the registry database and returned by the API. It is NOT stored as a raw YAML file in S3. The YAML representation shown here is the canonical serialization format for `fabricgate push` and human authoring.

The registry stores:
- Parsed fields in PostgreSQL (searchable, indexable)
- Platform Manifest files in S3 (content-addressed by digest)
- Artifact files in S3 (content-addressed by digest)
