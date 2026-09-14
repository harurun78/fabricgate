# Platform Manifest Schema

Version: 1.0.0-draft
Date: 2026-03-17
Parent: [README.md](./README.md)

> **Machine-readable schema:** [`docs/contracts/schemas/platform-manifest.schema.json`](../contracts/schemas/platform-manifest.schema.json) (generated SoT; this page is the human explanation).

---

## 1. Purpose

A Platform Manifest describes everything needed to apply a design on a specific platform. It is self-contained: given the manifest and its referenced artifacts, a runtime can operate without registry access.

Each runtime defines its own schema. The common envelope is minimal. This document defines:
1. Common envelope (all runtimes)
2. `pynq` runtime schema (MVP)
3. `linux-fpgamgr` runtime schema (MVP)
4. `nanopynq` runtime schema (Phase 3, included for forward reference)

### 1.1 対象 runtime とスコープ（ADR-010）

対象 runtime は `pynq` / `linux-fpgamgr` / `nanopynq` の 3 つ。
**XRT/Alveo（`.xclbin`）は対象外**とする（[ADR-010](../adr/010-xrt-alveo-out-of-scope.md)、再開条件付き）。

- `runtime` discriminated union への将来の `xrt` runtime 追加は**加算的**に可能（新 runtime 追加は既存 manifest を壊さない）。実装は行わない。
- **再開条件**（いずれかを満たしたら XRT/Alveo 対応の Issue を再オープン。詳細は ADR-010 参照）:
  1. Alveo/XRT ユーザーからの具体的な配布需要、またはスポンサー候補からの要望が観測される。
  2. `.xclbin` の取り扱い実態（PYNQ-on-XRT が無改変で consume するか、変換・付随ファイルが要るか）の追加調査が完了する。

## 2. Common Envelope

All Platform Manifests share this outer structure:

```yaml
schema: fabricgate-platform/v1
runtime: <runtime-id>          # Which runtime this manifest targets
board: <board_id>              # Board DB canonical ID (e.g., "zcu104", "generic-xczu7ev")
device_family: <string>        # Derived from Board DB (e.g., "xczu7ev"). Informational.
design_ref: <namespace>/<design>:<version>  # Back-reference to parent Design Index

# Runtime-specific content follows (varies by runtime)
artifacts: { ... }
interfaces: [ ... ]            # Optional: declared IP interfaces
dependencies: [ ... ]          # Optional: required companion designs

# Shell lifecycle (applicable only when bitstream_type: shell)
status: deprecated | yanked    # Optional: set by Shell namespace owner
```

### 2.1 `design_ref`

Back-reference to the Design Index that contains this Platform Manifest. Used for provenance tracking and cache key generation.

Format: `{namespace}/{design}:{version}`

### 2.2 `artifacts`

Each runtime defines its own artifact schema. The common requirement:
- Every artifact file MUST have a `sha256` digest
- Filenames are relative to the manifest directory

### 2.3 `interfaces` (optional)

Declared IP interfaces, for documentation and cross-platform consistency linting.

```yaml
interfaces:
  - name: <string>             # IP instance name (e.g., "dsp0", "dma0")
    type: <string>             # Interface type (e.g., "axi-lite", "axi-stream", "gpio")
    base: <hex-string>         # Base address (optional, runtime-dependent)
    description: <string>      # Human-readable (optional)
```

This field is informational. Runtimes MAY ignore it. Tools MAY use it to warn when two Platform Manifests in the same Design Index declare different interface sets.

### 2.4 `dependencies` (optional)

Platform レベルの依存関係。このビットストリームの動作に必要な伴走 Design（ソフトウェアドライバ、帄原となるオーバーレイ、追加ビットストリーム等）を定義する。

```yaml
dependencies:
  - name: xilinx/axi-dma              # namespace/design
    version: ">=1.0.0 <2.0.0"         # バージョンコンストレイント
    platform: xczu7ev/pynq            # Optional: デフォルトは親と同じ platform
    optional: false                   # Optional: デフォルト false
```

#### `name`

Format: `{namespace}/{design}` — `DesignName` 形式と共通

#### `version`

SemVer コンストレイント文字列。スペース区切りの複数述語を容認する。

| 記法 | 意味 | 例 |
|---|---|---|
| `=1.2.0` | 完全一致 | `=1.2.0` |
| `>=1.0.0 <2.0.0` | 範囲指定 | `>=1.0.0 <2.0.0` |
| `^1.2.0` | MAJOR 一致 (caret) | `>=1.2.0 <2.0.0` 相当 |
| `~1.2.0` | MINOR 一致 (tilde) | `>=1.2.0 <1.3.0` 相当 |
| `*` | 任意バージョン | 最新 stable |

#### `platform`

省略時は親 Platform Manifest と同じ platform に解決する。別 platform のビットストリームを依存する場合に明示する。

#### `optional`

`true` の場合、依存先が存在しなくても pull は成功する。欠如機能のみ失われる採オプション依存用。

#### 制約

- 1 Platform Manifest 内の `dependencies` エントリは最大 20 件
- 依存深度の最大値は 10（resolve 時にサーバーが緻出）
- 循環依存は publish 時にサーバーのバリデーションで检知・拒否する

---

### 2.5 `bitstream_type` (optional)

ビットストリームの部分的再構成（Partial Reconfiguration, PR / DFX）における種別を宣言する。

```yaml
bitstream_type: partial          # "shell" | "partial" — 省略時はスタンドアロン
```

| 値 | 意味 |
|---|---|
| `"shell"` | Static Shell ビットストリーム。PR の基礎となる完全ビットストリームで、Partial Module を受け入れる Reconfigurable Region (PBlock) を含む |
| `"partial"` | Partial Module ビットストリーム。Static Shell 上の特定 PBlock を部分的に再構成する |
| 省略 | スタンドアロン設計（PR 非対応の通常ビットストリーム）|

**制約:**
- `bitstream_type: partial` を持つ Platform Manifest は `shell_dependency` を必須とする
- `bitstream_type: shell` は `shell_dependency` を持ってはならない（依存深度最大 1 段）
- `bitstream_type: shell` の Platform Manifest は publish 時にレジストリへの登録が必要（`shell_dependency` の解決に使用）
- 1 Design Index 内の全 Platform Manifest は同一の `bitstream_type` を共有すること（publish 時制約、不一致時は `BITSTREAM_TYPE_CONFLICT` エラー）

---

### 2.6 `shell_dependency` (`bitstream_type: partial` のみ)

Partial Module が依存する Static Shell デザインを指定する。バイナリレベルの互換性のため、バージョンは**完全一致のみ**有効。

```yaml
shell_dependency:
  name: xilinx/base-overlay        # namespace/design (DesignName 形式)
  version: "=1.2.3"               # EXACT match only — 範囲指定は無効
  sha256: aabbccdd...             # Required: シェルビットストリームの 64-hex SHA-256
```

#### `version`

`=X.Y.Z` 形式のみ受け付ける。ソフトウェア依存の `dependencies` フィールドとは異なり、範囲指定（`>=`、`^`、`~`）は**禁止**。

**理由**: Partial Module は、コンパイル時に参照した Static Shell と完全に同一のビットストリームに対してのみバイナリ互換性が保証される（PBlock ルーティング・クロック分岐・デカップリングロジックは固定）。

#### `sha256`

**必須**（省略時はスキーマバリデーションで 400 `SCHEMA_VALIDATION_FAILED`）。値の定義（[ADR-009](../adr/009-shell-dependency-sha256-target.md)）:

> **参照する Shell design の、この partial と同一 platform（`board_id/runtime`）における配布 bitstream アーティファクトのバイト列の SHA-256**（= 当該アーティファクトの `ArtifactRef.sha256` と同一系の値）。

- 意味論は **「特定ビルドへの pin」** であり、実装互換性の証明ではない。同一の static 実装から再生成された別バイト列（タイムスタンプ差等）は非互換と判定される — false-incompatible（安全側）を許容する。
- publish 時および shell 解決時に、解決された shell platform の bitstream アーティファクトの `sha256` と**完全一致**しなければ失敗する（422 `DIGEST_MISMATCH`）。
- **検証不能な pin も失敗する**: 解決された shell platform に既知拡張子の bitstream アーティファクトが見つからない場合、照合スキップではなく 422 `DIGEST_MISMATCH` でリジェクトする（安全フロアに黙認の穴を作らない。ADR-009 追補）。「既知拡張子」は当該 runtime の allowlist で判定する（ADR-011 と同一セマンティクス）。

#### 制約

- `bitstream_type: partial` の場合は必須（省略時、publish は 422 `SHELL_DEPENDENCY_REQUIRED` でリジェクト）
- `bitstream_type: shell` または `bitstream_type` 省略の場合は指定禁止（指定時、422 `INVALID_BITSTREAM_TYPE_FOR_FIELD` でリジェクト）
- 指定した Shell デザインは publish 時点でレジストリに存在しなければならない（422 `SHELL_NOT_FOUND`）
- Shell デザインの `bitstream_type` は `"shell"` でなければならない（422 `INVALID_SHELL_BITSTREAM_TYPE`）
- Shell と Partial の `device_family`（Board DB から導出）は一致しなければならない（422 `DEVICE_MISMATCH`）

---

### 2.7 `status` (`bitstream_type: shell` のみ)

Shell ライフサイクルステータス。Shell ネームスペースオーナーが設定する。省略時は `null`（アクティブ）。

```yaml
status: deprecated             # "deprecated" | "yanked" | 適用外
```

| 値 | 意味 | `fabricgate pull` 時の挙動 |
|-----|------|-------------------|
| 省略 / null | アクティブ | 経路なし |
| `deprecated` | 非推奨。代替シェルへの移行を推奨 | `⚠ Warning: shell dependency is deprecated` 表示。pull は成功 |
| `yanked` | 配布停止。新規 RM の push 不可 | 既存 pull: `⚠ yanked` 警告付きで成功。新規登録: `SHELL_YANKED` エラー |

**制約:**
- `status` は `bitstream_type: shell` の Manifest にのみ適用する。それ以外のデザインに設定しても無視される
- Shell の delete は禁止。yank を使用する（left-pad 問題回避 + 永続性保証）

---

### 2.8 `tool_requirements` (optional)

ビットストリーム生成に使用したツールチェーンを記述する情報メタデータ。ライセンス遵守はユーザーの責任。

```yaml
tool_requirements:
  - tool: vivado                   # 必須: ツール識別子（小文字英数字とハイフン）
    min_version: "2024.1"         # Optional: 最低バージョン
    edition: standard             # Optional: "standard" | "enterprise" | "pro" | "lite"
    required: true                # Optional: デフォルト true。false = 代替ツールあり
    note: "DFX feature required"  # Optional: 補足説明（256文字以内）
  - tool: f4pga
    required: false
    note: "open source alternative (PR support in progress)"
```

`bitstream_type: partial` の場合、少なくとも 1 件の `tool_requirements` エントリを推奨する（PR の再生成には同一ツール・バージョンが必要なため）。

#### 対応ツール識別子（参考）

| 識別子 | ツール | 備考 |
|--------|--------|------|
| `vivado` | AMD Xilinx Vivado | Standard/Enterprise。PR は Standard で利用可 |
| `vitis` | AMD Xilinx Vitis / Vitis HLS | HLS IP 生成用 |
| `quartus` | Intel Quartus Prime | PR（Partial Reconfiguration）は Pro Edition のみ |
| `lattice-diamond` | Lattice Diamond | ECP5 等 |
| `radiant` | Lattice Radiant | iCE40/ECP5 UltraPlus |
| `libero` | Microchip Libero | PolarFire |
| `f4pga` | F4PGA (OSS) | Xilinx/Lattice。PR サポートは開発中 |
| `icestorm` | Project IceStorm (OSS) | iCE40 |
| `trellis` | Project Trellis (OSS) | ECP5 |

**ライセンス注記**: FabricGate はビットストリームのみを配布する。ツールチェーンのライセンス遵守はデザイン作成者の責任である。

---

### 2.9 bitstream コンテナ形式 — 拡張子を正とする（ADR-011）

bitstream のコンテナ形式に**型次元（enum フィールド）は存在しない**。`artifacts.bitstream.file`（`ArtifactRef.file`）の**ファイル拡張子を形式の正**とする（[ADR-011](../adr/011-bitstream-container-format-by-extension.md)）。

- FabricGate は形式変換をしない（Non-Goal）。manifest は具体ファイルを列挙し、pull はそのまま配布する。形式の整合責任は publisher（正しい形式でビルドする）と runtime（期待形式を知っている）にある。
- publish 時バリデーションは、runtime ごとの**既知拡張子 allowlist** を検査し、allowlist 外の拡張子は **WARNING のみ**とする（**エラーにしない・リジェクトしない**）。
- allowlist はサーバ側の**運用値**であり公開契約ではない。新形式（`.pdi` / `.rbf` 等）対応は allowlist と本ドキュメントの更新のみで済む（契約変更なし）。

#### runtime 別既知拡張子 allowlist（運用値）

| runtime | 既知拡張子 |
|---------|-----------|
| `pynq` | `.bit` |
| `linux-fpgamgr` | `.bit`, `.bin` |
| `nanopynq` | `.bin` |

実装: `fabricgate.models.platform_manifest.KNOWN_BITSTREAM_EXTENSIONS`

> **注**: ADR-011 の allowlist 例では `nanopynq` → `.bit` としているが、本スキーマ §5.2/§5.3 の通り nanopynq の形式は raw bitstream の `.bin` であり `.bit` ではない（iCE40 等）。運用値の allowlist は §5.2 に従い `.bin` のみとし、`.bit` のアップロードには ADR-011 の warning を出す（warning のみ・リジェクトしない）。

#### デバイスファミリ × runtime × 期待形式マトリクス（知識。契約ではない）

| デバイスファミリ | runtime | 期待形式 | 備考 |
|------------------|---------|----------|------|
| Zynq-7000 / Zynq UltraScale+ | `pynq` | `.bit` | PYNQ Overlay は `.bit` + `.hwh` |
| Zynq-7000 | `linux-fpgamgr` | `.bin` | fpga_manager は Bootgen 変換した `.bin` が典型 |
| Zynq UltraScale+ | `linux-fpgamgr` | `.bit` / `.bin` | カーネル・ボード構成に依存 |
| iCE40（pico-ice 等） | `nanopynq` | `.bin` | raw bitstream（§5.2） |
| Versal | —（将来） | `.pdi` | 対応時に allowlist 更新（契約変更なし） |
| Intel | —（将来） | `.rbf` | 対応時に allowlist 更新（契約変更なし） |
| Alveo（XRT） | —（対象外） | `.xclbin` | ADR-010 により対象外 |

---

For PYNQ Overlay-based designs on Zynq / Zynq UltraScale+.

### 3.1 Schema

```yaml
schema: fabricgate-platform/v1
runtime: pynq
board: <board_id>               # Board DB canonical (e.g., "zcu104", "generic-xczu7ev")
device_family: <string>         # Derived from Board DB (e.g., "xczu7ev")
design_ref: <namespace>/<design>:<version>

artifacts:
  bitstream:
    file: <filename>.bit
    sha256: <64-hex>
  hwh:                           # Required for PYNQ
    file: <filename>.hwh
    sha256: <64-hex>
  dtbo:                          # Optional: device tree overlay
    file: <filename>.dtbo
    sha256: <64-hex>

# Optional
pynq_version: <version-spec>    # Minimum PYNQ version (e.g., ">=3.0.1")
design_portability: <string>    # "axi-only" | "board-specific" | "io-constrained" (fabricgate build auto-detected)
status: deprecated | yanked     # Shell lifecycle. Shell manifests only (bitstream_type: shell)

# PR support (optional)
bitstream_type: <shell|partial>  # Omit for standalone
shell_dependency: { ... }       # Required when bitstream_type: partial
tool_requirements: [ ... ]      # Recommended when bitstream_type: partial

interfaces: [ ... ]              # Optional
```

### 3.2 Required Artifacts

| Artifact | Required | Purpose |
|----------|----------|---------|
| `bitstream` | Yes | FPGA configuration binary |
| `hwh` | Yes | Vivado hardware handoff — PYNQ uses this for IP discovery |
| `dtbo` | No | Device tree overlay for Linux driver binding |

### 3.3 Usage Pattern

```python
from fabricgate import pull
from pynq import Overlay

path = pull("xilinx/axi-dma-demo:1.2.0", platform="zcu104/pynq")
ol = Overlay(f"{path}/design.bit")
ol.download()
# IP is auto-discovered from .hwh
print(ol.ip_dict)
```

### 3.4 Example

```yaml
schema: fabricgate-platform/v1
runtime: pynq
board: zcu104
device_family: xczu7ev
design_ref: fabricgate/blink:1.0.0

artifacts:
  bitstream:
    file: blink.bit
    sha256: aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd
  hwh:
    file: blink.hwh
    sha256: 11223344112233441122334411223344112233441122334411223344112233445

pynq_version: ">=3.0.1"

tool_requirements:
  - tool: vivado
    min_version: "2023.2"
    edition: standard

interfaces:
  - name: axi_gpio_0
    type: axi-lite
    base: "0x41200000"
    description: "LED GPIO controller"
```

### 3.5 Example (Partial Module)

```yaml
schema: fabricgate-platform/v1
runtime: pynq
board: zcu104
device_family: xczu7ev
design_ref: community/fft-accel:1.0.0

artifacts:
  bitstream:
    file: fft_accel.partial.bit
    sha256: 99aabb00112233445566778899aabb00112233445566778899aabb0011223344
  hwh:
    file: fft_accel.hwh
    sha256: aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122

bitstream_type: partial
shell_dependency:
  name: community/zcu104-shell
  version: "=1.2.0"
  sha256: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef

tool_requirements:
  - tool: vivado
    min_version: "2024.1"
    edition: standard
    note: "DFX flow (Partial Reconfiguration)"

pynq_version: ">=3.0.1"

interfaces:
  - name: fft_ip_0
    type: axi-lite
    base: "0x43C00000"
    description: "FFT accelerator control registers"
```

For Linux FPGA Manager / FPGA Region based designs. Typically used for production/operational deployment on Zynq.

### 4.1 Schema

```yaml
schema: fabricgate-platform/v1
runtime: linux-fpgamgr
board: <board_id>               # Board DB canonical (e.g., "zcu104")
device_family: <string>         # Derived from Board DB (e.g., "xczu7ev")
design_ref: <namespace>/<design>:<version>

artifacts:
  bitstream:
    file: <filename>.bit
    sha256: <64-hex>
  dtbo:                          # Recommended for driver binding
    file: <filename>.dtbo
    sha256: <64-hex>
  modules:                       # Optional: kernel modules
    - file: <filename>.ko
      sha256: <64-hex>
      module_name: <string>      # modprobe name

# Optional
kernel_version: <version-spec>   # e.g., ">=5.15"
design_portability: <string>    # "axi-only" | "board-specific" | "io-constrained" (fabricgate build auto-detected)
status: deprecated | yanked     # Shell lifecycle. Shell manifests only (bitstream_type: shell)

# PR support (optional)
bitstream_type: <shell|partial>  # Omit for standalone
shell_dependency: { ... }       # Required when bitstream_type: partial
tool_requirements: [ ... ]      # Recommended when bitstream_type: partial

# Optional: post-load actions
post_load:
  services: [<string>, ...]      # systemd service names to start after FPGA load
  health_check:                  # Optional: verify design is operational
    type: <register-read|service-status>
    params: { ... }

interfaces: [ ... ]
```

### 4.2 Required Artifacts

| Artifact | Required | Purpose |
|----------|----------|---------|
| `bitstream` | Yes | FPGA configuration binary |
| `dtbo` | Recommended | Device tree overlay for bridge/driver setup |
| `modules[]` | No | Kernel modules (.ko) to load after FPGA programming |

### 4.3 Post-Load Actions

For operational use, the manifest can declare what happens after FPGA programming:

- `services`: systemd service units to (re)start
- `health_check`: verify the design is alive
  - `register-read`: Read a status register via `/dev/mem` or UIO
  - `service-status`: Check a systemd service reached `active` state

### 4.4 Usage Pattern

```bash
# Pull
fabricgate pull xilinx/axi-dma-demo:1.2.0 --platform zcu104/linux-fpgamgr

# Apply (manual)
sudo fpgautil -b design.bit -o design.dtbo
sudo modprobe gesture
sudo systemctl start gesture-daemon

# Or via Board Manager Daemon (Phase 2: web-framework)
board-mgr apply fabricgate/blink:1.0.0
```

### 4.5 Example

```yaml
schema: fabricgate-platform/v1
runtime: linux-fpgamgr
board: zcu104
device_family: xczu7ev
design_ref: fabricgate/blink:1.0.0

artifacts:
  bitstream:
    file: blink.bit
    sha256: eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011
  dtbo:
    file: blink.dtbo
    sha256: 5566778855667788556677885566778855667788556677885566778855667788

kernel_version: ">=5.15"

tool_requirements:
  - tool: vivado
    min_version: "2023.2"
    edition: standard

post_load:
  health_check:
    type: register-read
    params:
      address: "0x41200000"
      expected: "0x00000001"

interfaces:
  - name: axi_gpio_0
    type: axi-lite
    base: "0x41200000"
    description: "LED GPIO controller"
```


### 4.6 Example (Partial Module)

```yaml
schema: fabricgate-platform/v1
runtime: linux-fpgamgr
board: zcu104
device_family: xczu7ev
design_ref: community/fft-accel:1.0.0

artifacts:
  bitstream:
    file: fft_accel.partial.bit
    sha256: 99aabb00112233445566778899aabb00112233445566778899aabb0011223344
  dtbo:
    file: fft_accel.dtbo
    sha256: aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122aabb1122

bitstream_type: partial
shell_dependency:
  name: community/zcu104-shell
  version: "=1.2.0"
  sha256: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef

tool_requirements:
  - tool: vivado
    min_version: "2024.1"
    edition: standard
    note: "DFX flow (Partial Reconfiguration)"

kernel_version: ">=5.15"

interfaces:
  - name: fft_ip_0
    type: axi-lite
    base: "0x43C00000"
    description: "FFT accelerator control registers"
```

---

## 5. Runtime: `nanopynq` (Phase 3 — Forward Reference)

For MCU + external FPGA configurations (e.g., RP2040 + iCE40).

### 5.1 Schema

```yaml
schema: fabricgate-platform/v1
runtime: nanopynq
board: <board_id>               # Board DB canonical (e.g., "pico-ice")
device_family: <string>         # Derived from Board DB (e.g., "ice40up5k")
design_ref: <namespace>/<design>:<version>

artifacts:
  bitstream:
    file: <filename>.bin
    sha256: <64-hex>

# MCU-specific configuration
transport: <spi|pio|uart>        # MCU-to-FPGA communication method
mtu: <int>                       # Max transfer unit in bytes

# IP definitions (replaces .hwh for MCU context)
ips:
  <ip-name>:
    base: <hex-string>
    registers:
      <reg-name>: { offset: <hex>, width: <int> }
    streams:
      <stream-name>: { dir: <read|write>, mtu: <int> }

# Optional
mcu: <string>                    # MCU model (e.g., "rp2040")
design_portability: <string>    # "axi-only" | "board-specific" | "io-constrained" (fabricgate build auto-detected)

interfaces: [ ... ]
```

### 5.2 Key Differences from Linux Runtimes

- No `.hwh` — IP metadata is embedded directly as `ips` field
- No `.dtbo` — no Linux device tree
- No kernel modules — MCU runs MicroPython or bare-metal
- `transport` field declares physical link type
- Binary format is `.bin` (raw bitstream), not `.bit` (Vivado format)

### 5.3 Example

```yaml
schema: fabricgate-platform/v1
runtime: nanopynq
board: pico-ice
device_family: ice40up5k
design_ref: fabricgate/blink:1.0.0

artifacts:
  bitstream:
    file: blink.bin
    sha256: 22334455223344552233445522334455223344552233445522334455223344556

transport: spi
mtu: 1024
mcu: rp2040

ips:
  gpio0:
    base: "0x0000"
    registers:
      LED_CTRL: { offset: "0x00", width: 8 }
      LED_STATUS: { offset: "0x04", width: 8 }

interfaces:
  - name: gpio0
    type: gpio
    description: "LED GPIO controller"
```

---

## 6. Validation Rules (Common)

| Rule | Severity |
|------|----------|
| `schema` must be `fabricgate-platform/v1` | Error |
| `runtime` must be a known runtime identifier | Error (strict) / Warning (permissive) |
| `board` must be non-empty, match Board DB canonical ID format (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`) | Error |
| `design_ref` must match `namespace/design:version` format | Error |
| `artifacts.bitstream` must be present | Error |
| `artifacts.bitstream.sha256` must be valid 64-hex | Error |
| `bitstream_type` must be `"shell"` or `"partial"` if present | Error |
| `bitstream_type: partial` requires `shell_dependency` | Error |
| `bitstream_type: shell` or absent forbids `shell_dependency` | Error |
| `shell_dependency.version` must match `=X.Y.Z` (exact match only) | Error |
| Shell design referenced by `shell_dependency.name` must exist in registry (publish-time) | Error |
| Shell design must have `bitstream_type: shell` | Error |
| `device_family` of partial must match `device_family` of shell (resolved via Board DB) | Error |
| All platforms in a Design Index must share the same `bitstream_type` | Error (publish-time) |
| `tool_requirements[].tool` must match `^[a-z][a-z0-9-]*$` | Error |
| All artifact files must exist in the manifest directory | Error (local validation) |
| `interfaces` entries should have unique `name` | Warning |
| `artifacts.bitstream.file` の拡張子が runtime の既知拡張子 allowlist 外（§2.9, ADR-011） | Warning |
| `attestation.bundle` present → `attestation.transparency_log_url` must be non-empty | Error |

## 6.5 `attestation` (optional)

アーティファクトのサプライチェーン完全性を証明する Sigstore / cosign 署名バンドルフィールド。
publish 時はオプション。`fabricgate pull --verify-attestation` 指定時に CLI が検証する。

```yaml
attestation:
  bundle: "cosign.bundle"       # アーティファクトと同ディレクトリに配置
  transparency_log_url: "https://rekor.sigstore.dev"
```

| フィールド | 型 | 説明 |
|---|---|---|
| `bundle` | string | Cosign バンドルファイル名（アーティファクトと同ディレクトリ） |
| `transparency_log_url` | string | Rekor 互換 transparency log の URL |

> **注意:** FabricGate はバンドルファイルの内容をバリデーションしない。CLI の `--verify-attestation` フラグが cosign CLI を呼び出して検証する。サーバーはバンドルファイルを他のアーティファクトと同様にストレージに保存するのみ。

## 7. Extensibility

New runtimes are added by:

1. Choosing a `runtime` identifier (e.g., `my-custom-runtime`)
2. Defining the runtime-specific fields (artifacts, config)
3. Implementing a CLI plugin or runtime adapter that understands the schema
4. Registering the runtime with FabricGate (optional — permissive mode allows unknown runtimes)

The common envelope (`schema`, `runtime`, `device`, `design_ref`, `artifacts.bitstream`) is stable. Runtime-specific fields can evolve independently.
