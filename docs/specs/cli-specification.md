# CLI Specification

Version: 1.1.0-draft
Date: 2026-04-13
Parent: [README.md](./README.md)

---

## 1. Overview

`fabricgate` is the FabricGate command-line tool. It provides a unified interface for pulling, pushing, searching, and verifying FPGA designs across all platforms. The short alias `fgate` is installed as an equivalent entry point.

> **Note — why not `fg`?** `fg` is a POSIX shell builtin (job-control "foreground") present in every interactive bash/zsh session, and shell builtins shadow `PATH` executables. A command named `fg` would therefore be intercepted by the shell and never reach the installed binary. The canonical command is `fabricgate`; `fgate` is provided as a short, non-conflicting alias.

**Installation:**
```bash
pip install fabricgate
```

**Design Principle:** Same command, same UX, any platform. The `--platform` flag is the only differentiator.

## 2. Global Options

```
fabricgate [--registry <url>] [--platform <board_id/runtime>] [--cache-dir <path>] [--verbose] <command>
```

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--registry` | `FG_REGISTRY` | `https://registry.fabricgate.dev/api/v1` | Registry base URL |
| `--platform` | `FG_PLATFORM` | (none) | Default platform for pull (format: `board_id/runtime`) |
| `--cache-dir` | `FG_CACHE_DIR` | `~/.fabricgate/cache` | Local cache directory |
| `--verbose` | — | false | Verbose output |
| `--json` | — | false | JSON output (machine-readable) |

## 2.1 Exit Code Conventions

Exit codes are a machine-readable contract for scripting (`$?`). They follow a
**semantic standard** shared by every command (see [ADR-008](../adr/008-cli-exit-code-standard.md)).
A given kind of failure produces the same code in every subcommand.

| Code | Meaning | Examples |
|------|---------|----------|
| 0 | Success | — |
| 1 | Not found / generic | named resource absent (design / version / namespace / key); unclassified error |
| 2 | Permission | not authenticated (run `fabricgate login`), 401/403, scope not allowed |
| 3 | Invalid / conflict | digest mismatch, attestation failure, insecure webhook URL, rate-limited (429), limit exceeded, version conflict |
| 4 | Infrastructure | network error, server 5xx, local write failure, Board DB load failure, cosign not installed |
| 5 | Unresolvable selection | platform not found, dependency unresolvable |
| 6 | Shell not found | partial bitstream shell unresolvable |

The per-command **Exit codes** sections below list the subset each command can
emit (with command-specific phrasing), but the code values always conform to
this table. New commands MUST follow it. Commands without an **Exit codes**
section (e.g. `info` / `verify` / `search`) emit only the standard codes above.

> **Permission (2) on read commands**: read コマンド（`pull` / `diff` / `info` /
> `stats` / `quota` / `watch` / `license-check`）が叩くレジストリのリードエンドポイントは
> 現状すべて public で 401/403 を返さない。終了コードは全コマンド共通のマッピングを通るため、
> private namespace/design へのアクセス制御が有効化された際は 401/403 が一律 exit 2 にマップされる
> （前方互換契約）。書き込み系（`push` / `yank` / `deprecate` / `token` / `webhook`）は現時点で認可必須のため 2 は到達可能。

## 3. Commands

### 3.1 `fabricgate pull`

Download a design for a specific platform.

```
fabricgate pull <design-ref> [--platform <board_id/runtime>] [--output <dir>] [--verify] [--no-deps] [--deps-only]
```

**Arguments:**
- `<design-ref>`: `namespace/design:version` (e.g., `fabricgate/blink:1.0.0`)

**Options:**
- `--platform`: Target platform (format: `board_id/runtime`). If omitted, uses `FG_PLATFORM` env var. If neither is set and multiple platforms exist, shows selection prompt. Resolution is two-stage: exact match first; on miss, if `board_id` is a Board DB-registered real board (not `generic-*`), falls back to `generic-{device_family}/{runtime}` (family fallback, see below).
- `--output`: Output directory (default: `./<design>-<version>/`)
- `--verify`: Verify all artifact checksums after download (default: true)
- `--verify-attestation`: アーティファクトの Sigstore/cosign アテステーションを検証する（cosign CLI が必要）
- `--no-deps`: 依存記述を無視してルート Design のみ取得する
- `--deps-only`: 依存 Design のみ取得し、ルートはスキップする（事前にディレクトリを用意する場合等）
- `--include-optional-deps`: optional 依存も取得する（default: 無効）
- `--no-shell`: `bitstream_type: partial` のデザインにおいて Shell の自動取得をスキップする（Shell が既にローカルにある場合等）

**Behavior:**

```
$ fabricgate pull fabricgate/blink:1.0.0 --platform zcu104/pynq

Resolving fabricgate/blink:1.0.0 ...
  Found 2 platforms: zcu104/pynq, zcu104/linux-fpgamgr
  Selected: zcu104/pynq

Resolving dependencies ...
  xilinx/axi-dma:1.5.2   (required by fabricgate/blink)
    xilinx/axi-interconnect:2.0.0   (required by xilinx/axi-dma)

Downloading fabricgate/blink:1.0.0 ...
  blink.bit  [============] 256 KB  sha256:aabb...✓
  blink.hwh  [============]  12 KB  sha256:1122...✓

Downloading xilinx/axi-dma:1.5.2 ...
  axi-dma.bit  [============] 128 KB  sha256:ccdd...✓
  axi-dma.hwh  [============]   8 KB  sha256:3344...✓

Downloading xilinx/axi-interconnect:2.0.0 ...
  ...

Saved to ./blink-1.0.0/
  blink.bit
  blink.hwh
  manifest.yaml
  deps/
    xilinx-axi-dma-1.5.2/
    xilinx-axi-interconnect-2.0.0/
```

**Partial Reconfiguration (PR) デザインの取得:**

`bitstream_type: partial` の Platform Manifest を含むデザインを pull する場合、依存 Static Shell を自動的に先行取得する。

```
$ fabricgate pull community/fft-accel:1.0.0 --platform zcu104/pynq

Resolving community/fft-accel:1.0.0 ...
  bitstream_type: partial
  Shell dependency: community/zcu104-shell =1.2.0

Downloading shell: community/zcu104-shell:1.2.0 ...
  zcu104_shell.bit  [============] 8 MB  sha256:dead...✓

Downloading community/fft-accel:1.0.0 ...
  fft_accel.bit  [============] 512 KB  sha256:cafe...✓
  fft_accel.hwh  [============]  14 KB  sha256:beef...✓

Saved to ./fft-accel-1.0.0/
  fft_accel.bit
  fft_accel.hwh
  manifest.yaml
  shell/
    community-zcu104-shell-1.2.0/
      zcu104_shell.bit
      manifest.yaml
```

Shell が既にローカルに存在する場合、またはユーザーが手動管理する場合は `--no-shell` を指定する:

```
$ fabricgate pull community/fft-accel:1.0.0 --platform zcu104/pynq --no-shell
  ⚠  Shell dependency skipped: community/zcu104-shell =1.2.0
     Ensure shell bitstream is present before loading.
```

**Family fallback（実ボード id → generic platform）:**

`--platform` の完全一致が無い場合、`board_id` を Board DB で `device_family` に解決し、
`generic-{device_family}/{runtime}` の entry を再探索する（2 段解決。契約は
`client-behavior.md` §6 が正）。フォールバックで選択した場合は**由来を明示**する:

```
$ fabricgate pull fabricgate/hello:1.0.0 --platform pynq-z2/pynq

Selected: generic-xc7z020/pynq (family fallback from pynq-z2/pynq)
Saved to ./hello-1.0.0/
  hello.bit
  hello.hwh
```

- 完全一致が存在する場合はフォールバックしない（従来挙動不変）。
- Board DB に無い board_id はフォールバックせず従来どおりエラー（exit code 5）。
- フォールバック先の entry も無ければ従来どおりエラー（exit code 5、利用可能 platform 一覧付き）。

**When platform is ambiguous:**
```
$ fabricgate pull fabricgate/blink:1.0.0

Resolving fabricgate/blink:1.0.0 ...
  Found 2 platforms:
    1. zcu104/pynq
    2. zcu104/linux-fpgamgr

  Specify --platform or set FG_PLATFORM env var.
  Example: fabricgate pull fabricgate/blink:1.0.0 --platform zcu104/pynq
```

**Deprecated バージョン指定時の警告:**

```
$ fabricgate pull community/fft-accel:1.0.0 --platform zcu104/pynq

⚠  community/fft-accel:1.0.0 is deprecated.
   Use community/fft-accel:2.0.0 instead.
   Downloading anyway...

Downloading community/fft-accel:1.0.0 ...
  ...
```

**認証と帰属（API-KPI-001）:**

pull は認証不要（public）だが、ログイン済み（保存済み認証情報あり）の場合は
Authorization ヘッダを自動付与し、ダウンロード統計の pull 主体帰属
（オーガニック pull 率 KPI、`docs/notes/kpi-organic-pulls.md`）に利用される。
未ログイン・認証情報ストア読込失敗・トークン無効のいずれでも pull は従来どおり
匿名で成功する（公開契約不変）。SDK の `pull(..., token=...)` で明示指定した場合は
保存済み認証情報を参照しない。

**Exit codes:**
- 0: Success（deprecated 版を pull した場合も 0）
- 1: Design / version not found
- 2: Permission（private/access-controlled な namespace・design への 401 / 403）
- 3: Digest mismatch / attestation failure (integrity failure)
- 4: Network error / ローカル書込失敗 / cosign 未導入 (`--verify-attestation` 時)
- 5: Platform not found / dependency unresolvable (version constraint を満たすバージョンが存在しない)
- 6: Shell not found (`bitstream_type: partial` の shell_dependency が解決不能)

---

### 3.2 `fabricgate push`

Publish a design to the registry.

```
fabricgate push <directory> [--namespace <ns>] [--yes] [--skip-sha-check] [--artifact-url <filename>=<url>]...
```

**Arguments:**
- `<directory>`: Directory containing a Design Index (`fabricgate-index.yaml`) and platform subdirectories.

**Options:**

| Option | Description |
|---|---|
| `--namespace` | ネームスペースを上書きする |
| `--yes` | AXI-only の `custom-*` デザインを `generic-*` プラットフォームに自動昇格する（TTY プロンプトを省略） |
| `--skip-sha-check` | プレースホルダー sha256 (`a` × 64) の警告を抑制する（実際のハッシュ検証は行われる） |
| `--artifact-url <filename>=<url>` | `<filename>` をアップロードせず、既存の公開 `https` URL への参照として公開する（繰り返し可） |

**Expected directory structure:**

```
my-design/
  fabricgate-index.yaml           # Design Index
  README.md                       # Optional: displayed on registry web UI
  zcu104-pynq/                    # Platform: zcu104/pynq
    manifest.yaml                 # Platform Manifest
    design.bit
    design.hwh
  zcu104-linux-fpgamgr/           # Platform: zcu104/linux-fpgamgr
    manifest.yaml
    design.bit
    design.dtbo
```

**Behavior:**

```
$ fabricgate push ./my-design/

Validating Design Index ...                          ✓
Validating platform zcu104/pynq ...                  ✓
  Checking artifact: design.bit (sha256:aabb...  ✓)
  Checking artifact: design.hwh (sha256:1122...  ✓)
Validating platform zcu104/linux-fpgamgr ...         ✓
  Checking artifact: design.bit (sha256:aabb...  ✓)
  Checking artifact: design.dtbo (sha256:5566... ✓)

Publishing fabricgate/blink:1.0.0 ...
  Uploading zcu104/pynq artifacts ...                ✓
  Uploading zcu104/linux-fpgamgr artifacts ...        ✓

Published: fabricgate/blink:1.0.0 (2 platforms)
```

**Validation before upload:**
- Design Index schema validation
- All Platform Manifests schema validation
- All artifact files exist and match declared SHA-256 digests
- Design Index digests match computed Platform Manifest hashes
- `bitstream_type: partial` の場合、`shell_dependency` が指定されていること (`SHELL_DEPENDENCY_REQUIRED`)
- `shell_dependency` の参照先デザイン・バージョンがレジストリに存在すること (`SHELL_NOT_FOUND`)
- Design Index 内の全 Platform Manifest の `bitstream_type` が同一であること (`BITSTREAM_TYPE_CONFLICT`)

**custom-\* + axi-only デザインの汎用化プロンプト:**

`custom-*` ボードかつ `design_portability: axi-only` のプラットフォームが含まれる場合、アップロード前に以下の昇格プロンプトを表示する。

```
$ fabricgate push ./my-design/

Validating Design Index ...                          ✓
Validating platform custom-xczu7ev-ffvc1156/pynq ... ✓

  ℹ Board 'custom-xczu7ev-ffvc1156' is not in the Board DB.
    This design is AXI-only and can run on any xczu7ev board.
    Register as generic-xczu7ev/pynq instead? [y/N]: y

  ✓ Pushed as generic-xczu7ev/pynq

Published: myns/my-design:1.0.0 (1 platform)
```

N を選択した場合:

```
  ✓ Pushed as custom-xczu7ev-ffvc1156/pynq
  💡 You can expand visibility later from your design page.

Published: myns/my-design:1.0.0 (1 platform)
```

**プロンプト動作ルール:**

| 条件 | 動作 |
|---|---|
| TTY あり（対話セッション） | y/N プロンプトを表示（デフォルト N） |
| 非 TTY（CI/パイプライン） | 自動 N（プロンプトなし）、メッセージのみ出力 |
| `fabricgate push --yes` フラグ | 強制 y（AXI-only プラットフォームのみ適用） |
| `fabricgate push --yes` + board-specific デザイン | エラー：`--yes requires axi-only design` |

`custom-*` でない通常ボード、`design_portability: board-specific`、または `io-constrained` の場合はプロンプト不要。

**プレースホルダー SHA-256 の警告:**

`fabricgate build` が生成するマニフェストのアーティファクト sha256 は、ビルド直後は `aaaa...aaaa` (64字) のプレースホルダーになっている。実際のアーティファクトを配置した後、sha256 を正確な値に更新してから `fabricgate push` を実行すること。

プレースホルダーのまま push を試みると警告が表示される:

```
$ fabricgate push ./my-design/
⚠ Warning: artifact sha256 for design.bit is a placeholder (aaaa...aaaa).
    Tip: compute real artifact hashes after flashing to override the placeholder.
```

プレースホルダーでも push を続行したい場合（開発・テスト用途）:

```
$ fabricgate push ./my-design/ --skip-sha-check
```

`--skip-sha-check` は警告の抑制だけで、実際のハッシュが存在する場合の検証は省略しない。

**URL 参照による公開（`--artifact-url`）:**

GitHub Release 等に既に公開されているアーティファクトは、コピーをアップロードせずに URL で参照できる。
レジストリは publish 時に URL を 1 回取得して manifest の `sha256` と照合し、以後の download は
その URL へ 307 リダイレクトする（再ホストしない）。`pull` 側の挙動は変わらない。

```
$ fabricgate push ./my-design/ \
    --artifact-url design.bit=https://github.com/acme/blink/releases/download/v1.0.0/design.bit
```

| ルール | 内容 |
|---|---|
| 値の形式 | `<filename>=<url>`。`<filename>` は manifest の `artifacts[].file`。形式違反・同一 filename の重複は usage error（exit 2） |
| URL | `https` のみ。`http` 等は送信前に拒否する（exit 3）。ホスト allow-list・リダイレクト検査はサーバ側で行い、クライアントは持たない |
| 適用範囲 | 同じ filename を宣言する**すべての** platform に同じ URL を適用する |
| 相互排他 | URL 指定した filename については upload ticket を要求せず `artifact:` パートも送らない（[client-behavior §3.1](./client-behavior.md)）。同一ファイルに inline と URL の両方が届いた場合サーバは `400 INVALID_REQUEST` を返す |
| digest | manifest の `sha256` は URL 指定でも必須。プレースホルダー（`a` × 64）のままの URL 指定はエラー（サーバで必ず `DIGEST_MISMATCH` になるため）。ローカルにファイルがあれば従来どおり digest を照合し、無ければ manifest の値を信頼する |
| 未宣言 filename | どの manifest にも無い filename を指定するとエラー（exit 3） |

---

### 3.2b `fabricgate build`

HWH ファイルから Platform Manifest と Design Index を自動生成する。

```
fabricgate build <directory> [--namespace <ns>] [--version <semver>] [--tags <tag,...>]
                     [--hwh <path>] [--output <dir>] [--dry-run]
```

**Arguments:**
- `<directory>`: `.xsa` または HWH ファイルを含むディレクトリ。サブディレクトリも再帰検索する。

**Options:**

| Option | Description |
|---|---|
| `--namespace` | レジストリのネームスペース（省略時はインタラクティブに入力） |
| `--version` | SemVer バージョン（省略時はインタラクティブに入力） |
| `--tags` | カンマ区切りタグ（例: `dma,axi,zynq`） |
| `--hwh <path>` | `.hwh` ファイルを明示指定する。複数 HWH ファイルが見つかった場合は必須 |
| `--output <dir>` | 出力先ディレクトリ（デフォルト: カレントディレクトリに `<design_slug>/`） |
| `--dry-run` | ファイルを書き出さずに生成内容をプレビューする |

**複数 HWH ファイルの挙動:**

| 条件 | 動作 |
|---|---|
| HWH が 1 件 | 自動選択 |
| HWH が複数 + TTY あり | 番号選択プロンプト |
| HWH が複数 + 非 TTY | exit 1 + エラーメッセージ（`--hwh` で指定するよう促す） |

**生成フロー:**

1. `.hwh` の XML をパースし、`BOARDPART` 属性と `EXTERNALINTERFACES` を取得
2. `BOARDPART` が Board DB に存在する場合 → そのボードの `board_id` を使用
3. `BOARDPART` が Board DB に存在しない場合:
   - `EXTERNALINTERFACES` が全て AXI の場合 → `generic-{device_family}` を提案
   - board-specific な IP が含まれる場合 → `custom-{device}-{package}` を生成（確認あり）
4. `design_portability` を自動判定（`axi-only` / `board-specific` / `io-constrained`）
   - `axi-only`: 全てのインターフェースが AXI バスのみ
   - `board-specific`: ボード固有 IP（MIPI、HDMI 等）を使用
   - `io-constrained`: AXI バスれだが特定ピンのインターフェース制約あり（`generic-*` 昇格の対象外）
5. AXI マスター/スレーブアドレスマップを `interfaces` として抽出
6. 名前・バージョン・説明などをインタラクティブに入力
7. `fabricgate-manifest.yaml` と `fabricgate-index.yaml` を出力

**Behavior:**

```
$ fabricgate build ./vivado-project/

Scanning for HWH files ...
  Found: vivado-project/design_1_wrapper.hwh

Parsing HWH ...
  BOARDPART: xilinx.com:zcu104:part0:1.1
  → Board DB match: zcu104 (Xilinx ZCU104)
  EXTERNALINTERFACES: 2 AXI-Lite slaves
  → design_portability: axi-only

Design name [myns/]: myns/my-design
Version [0.1.0]: 1.0.0
Runtime: pynq
Description: My first design
Tags: dma, axi

Generated:
  ./my-design/fabricgate-index.yaml              ✓
  ./my-design/zcu104-pynq/manifest.yaml          ✓

Note: Place bitstream files in ./my-design/zcu104-pynq/ before publishing.
Run `fabricgate push ./my-design/` to publish.
```

**BOARDPART が Board DB にない場合（AXI-only）:**

```
  BOARDPART: myvendor.com:myboard:part0:1.0
  → Board DB: not found
  EXTERNALINTERFACES: AXI-only
  → Suggest: generic-xczu7ev

  Board 'myvendor.com:myboard' is not in the Board DB.
  Treat as generic-xczu7ev (AXI-only, any xczu7ev board)? [Y/n]: Y

  → platform: generic-xczu7ev/pynq
```

**BOARDPART が Board DB にない場合（board-specific）:**

```
  BOARDPART: myvendor.com:myboard:part0:1.0  (xczu7ev, ffvc1156)
  → Board DB: not found
  EXTERNALINTERFACES: board-specific IP detected (MIPI CSI-2)
  → Suggest: custom-xczu7ev-ffvc1156

  Platform will be registered as: custom-xczu7ev-ffvc1156/pynq
  Continue? [Y/n]: Y

  → platform: custom-xczu7ev-ffvc1156/pynq
```

**Exit codes:**
- 0: 生成成功
- 1: HWH ファイルが見つからない / HWH パース失敗 / 非 TTY で複数 HWH が見つかり `--hwh` 未指定 / Board DB 未登録ボードの確認プロンプトを中断
- 4: Board DB 読み込み失敗 / 生成先ディレクトリへの書き込み失敗（infrastructure）

---

### 3.3 `fabricgate search`

Search for designs in the registry.

```
fabricgate search [<query>] [--platform <board_id/runtime>] [--device <device_family>] [--runtime <runtime>] [--tag <tag>] [--board <board_id>]
```

**Options:**

| Option | Description |
|---|---|
| `--platform` | `board_id/runtime` 形式でプラットフォームを絞り込む（仮想ボード `generic-*`, `custom-*` も指定可） |
| `--device` | デバイスファミリー（`xczu7ev`, `xc7z020` など）で絞り込む |
| `--runtime` | ランタイム（`pynq`, `linux-fpgamgr`, `nanopynq`）で絞り込む |
| `--tag` | タグで絞り込む |
| `--board` | Board DB の `board_id` で絞り込む（`zcu104`, `pynq-z2` など） |

**Behavior:**

```
$ fabricgate search dma --platform zcu104/pynq

NAME                      VERSION   PLATFORMS              SUMMARY
xilinx/axi-dma-demo       2.0.1     pynq-z2/pynq +1       AXI DMA streaming demo
xilinx/axi-dma-sg         1.0.0     zcu104/pynq +1         AXI DMA scatter-gather
community/audio-stream    0.2.0     zcu104/pynq            Audio streaming via DMA
```

```
$ fabricgate search --device xczu7ev

NAME                      VERSION   PLATFORMS              SUMMARY
fabricgate/blink          1.0.0     zcu104/pynq +1         LED blink reference
xilinx/axi-dma-demo       2.0.1     zcu104/linux-fpgamgr   AXI DMA streaming demo
...
```

```
$ fabricgate search --board zcu104

NAME                      VERSION   PLATFORMS              SUMMARY
fabricgate/blink          1.0.0     zcu104/pynq +1         LED blink reference
community/zcu104-shell    1.2.0     zcu104/pynq            Official ZCU104 shell
...

---

### 3.3b `fabricgate diff`

2つのバージョン間のメタデータ差分を表示する。

```
fabricgate diff <design-ref> --base <base-version> [--platform <board_id/runtime>]
```

**Arguments:**
- `<design-ref>`: 比較先バージョン（`namespace/design:version`）

**Options:**

| Option | Description |
|---|---|
| `--base` | 比較元バージョン（必須）。`namespace/design:version` 形式 |
| `--platform` | 特定プラットフォームのみ比較（省略時は全プラットフォーム） |

**Behavior:**

```
$ fabricgate diff community/fft-accel:2.0.0 --base 1.0.0

Diff: community/fft-accel  1.0.0 → 2.0.0

 Platforms added:   pico-ice/nanopynq
 Platforms removed: (none)
 Platforms changed: zcu104/pynq

zcu104/pynq:
  bitstream_type      null → "partial"
  artifacts[0].sha256 aabb... → cafe...
  artifacts[0].size   256 KB → 512 KB
  tool_requirements   [] → [{tool: vivado, min_version: 2024.1}]

pico-ice/nanopynq:
  (added in 2.0.0)
```

**Exit codes:**
- 0: Success（差分あり・なし両方）
- 1: Design / version not found
- 2: Permission（private/access-controlled な namespace・design への 401 / 403）
- 3: Invalid design-ref / base-ref
- 4: Network error / server 5xx

---

### 3.4 `fabricgate verify`

Verify integrity of a pulled design.

```
fabricgate verify <directory>
```

**Behavior:**

```
$ fabricgate verify ./blink-1.0.0/

Verifying fabricgate/blink:1.0.0 (zcu104/pynq) ...
  blink.bit  sha256:aabb...  ✓
  blink.hwh  sha256:1122...  ✓

All artifacts verified.
```

---

### 3.5 `fabricgate info`

Show detailed information about a design.

```
fabricgate info <design-ref>
```

**Behavior:**

```
$ fabricgate info fabricgate/blink:1.0.0

Name:       fabricgate/blink
Version:    1.0.0
Summary:    LED blink reference design — multi-platform demo
License:    Apache-2.0
Author:     FabricGate Project
Repository: https://github.com/fabricgate/blink
Tags:       reference, blink, led, getting-started

Platforms:
  zcu104/pynq
    Board:       zcu104  (Xilinx ZCU104 Evaluation Board)
    Speed grade: min -2, tested [-2]
    Size:        256 KB
    Artifacts:   blink.bit, blink.hwh

  zcu104/linux-fpgamgr
    Board:       zcu104  (Xilinx ZCU104 Evaluation Board)
    Speed grade: min -2, tested [-2]
    Size:        258 KB
    Artifacts:   blink.bit, blink.dtbo
```

`--json` では `platforms[].artifacts[]` にサーバ応答の `filename` / `sha256` / `size` / `source` をそのまま出力する。
`source` は `"registry"`（レジストリ保管）または `"external"`（`push --artifact-url` による URL 参照。download は
その URL へリダイレクト）。`source` を返さない旧サーバでは `null` になる（加算的フィールド、ADR-014 tolerant reader）。

---

### 3.6 `fabricgate login`

Authenticate with the registry.

```
fabricgate login [--registry <url>]
```

**Behavior (OAuth Device Authorization Flow):**

```
$ fabricgate login

Using registry: https://registry.fabricgate.dev/api/v1

To authenticate, visit:
  https://registry.fabricgate.dev/device
  and enter code: ABCD-EFGH

Waiting for authorization ... ✓

Logged in. Token saved to OS keychain (registry.fabricgate.dev).
```

Token is stored in the **OS keychain** (Windows Credential Manager /
macOS Keychain / Linux Secret Service). Plaintext fallback to
`~/.fabricgate/credentials.json` (mode `0600`) is used only when
no keychain is available.

> Implementation: use [`keyring`](https://pypi.org/project/keyring/) library.
> Service name: `fabricgate`, username: registry hostname.

---

### 3.7 `fabricgate list`

List cached designs.

```
fabricgate list [--remote] [--namespace <ns>]
```

**Behavior (local cache):**

```
$ fabricgate list

DESIGN                     VERSION   PLATFORM              PULLED
fabricgate/blink           1.0.0     zcu104/pynq            2026-03-17
xilinx/axi-dma-demo        2.0.1     zcu104/linux-fpgamgr   2026-03-16
```

**Behavior (remote, own namespace):**

```
$ fabricgate list --remote --namespace fabricgate

DESIGN                     VERSION   PLATFORMS              PUBLISHED
fabricgate/blink           1.0.0     zcu104/pynq +1         2026-03-17
```

---

### 3.8 `fabricgate token`
> **Not available yet.** The hosted registry does not implement these endpoints, so this
> command group is hidden from `--help` and any call returns 404. Tracked in
> [issue #6](https://github.com/harurun78/fabricgate/issues/6).


API キー（machine token）の管理コマンド。CI/CD や自動化スクリプト向けの長期資格情報を作成・一覧・失効できる。

```
fabricgate token <subcommand>
```

#### サブコマンド一覧

| Subcommand | Description |
|---|---|
| `fabricgate token create` | 新しい API キーを作成する |
| `fabricgate token list` | API キーの一覧を表示する |
| `fabricgate token revoke` | API キーを失効させる |

---

#### `fabricgate token create`

```
fabricgate token create --name <name> [--scopes <scope,...>] [--expires <date>]
```

**Options:**

| Option | Required | Description |
|---|:---:|---|
| `--name` | ✓ | API キーの識別名（例: `ci-pipeline`） |
| `--scopes` | — | カンマ区切りスコープ（デフォルト: `public:read`） |
| `--expires` | — | 有効期限 ISO 8601 または相対表記（例: `90d`, `2027-01-01`） |

**Behavior:**

```
$ fabricgate token create --name ci-pipeline --scopes public:read,ns:alice:write --expires 90d

Creating API key "ci-pipeline" ...

  Name:    ci-pipeline
  Scopes:  public:read, ns:alice:write
  Expires: 2026-06-25T00:00:00Z

  Token: fgk_Abc123XYZ...

  ⚠  このトークンは一度だけ表示されます。安全な場所に保管してください。
     CI/CD 環境変数: FABRICGATE_TOKEN=fgk_Abc123XYZ...
```

**Exit codes:**
- 0: Success
- 2: Authentication required (未認証=要 `fabricgate login`) / scope not allowed (401 / 403)
- 3: Key limit exceeded (20 keys per user) / 不正な有効期限 (`--expires` が 3650 日超)
- 4: Network error / server 5xx

---

#### `fabricgate token list`

```
fabricgate token list [--json]
```

**Behavior:**

```
$ fabricgate token list

ID   NAME              SCOPES                          EXPIRES        LAST USED
1    ci-pipeline       public:read, ns:alice:write     2026-06-25     2026-03-27
2    deploy-script     public:read                     (never)        2026-03-20
```

---

#### `fabricgate token revoke`

```
fabricgate token revoke <id>
```

**Behavior:**

```
$ fabricgate token revoke 1

Revoke API key "ci-pipeline" (id: 1)? [y/N] y
Revoked.
```

**Options:**
- `--force`: 確認プロンプトをスキップ

**Exit codes:**
- 0: Success
- 1: Key not found
- 2: Authentication required (未認証=要 `fabricgate login`) / permission (401 / 403)
- 4: Network error / server 5xx

---

#### 環境変数による API キー認証

`fabricgate` コマンドへの API キーの渡し方は2通り:

```bash
# 環境変数（CI/CD 推奨）
export FABRICGATE_TOKEN=fgk_Abc123...
fabricgate push ./my-design/

# フラグ
fabricgate push ./my-design/ --token fgk_Abc123...
```

| Method | Env Var | Flag |
|---|---|---|
| API キー / OAuth トークン共通 | `FABRICGATE_TOKEN` | `--token` |

> **Note:** `FABRICGATE_TOKEN` が設定されている場合、OS キーチェーンの認証情報より優先される。

---

### 3.8b `fabricgate watch`

CI パイプライン向け: 指定デザインに新しいバージョン（またはシェル）が公開されたか確認する。

```
fabricgate watch <design-ref> [--shell <ns/design>] [--since-version <X.Y.Z>] [--platform <board_id/runtime>]
```

**Arguments:**
- `<design-ref>`: 監視対象デザイン（`namespace/design` 形式）

**Options:**

| Option | Description |
|---|---|
| `--shell` | シェルデザインの新バージョンを監視（`ns/design` 形式） |
| `--since-version` | このバージョンより新しいものを検索（省略時: 最新バージョン存在確認） |
| `--platform` | 特定プラットフォームのバージョンのみ確認（省略時: 任意のプラットフォームで判定） |

**Behavior:**

新バージョンが存在する場合（exit 0）:

```
$ fabricgate watch fabricgate/blink --since-version 1.0.0

New version found: fabricgate/blink:1.1.0  (platforms: zcu104/pynq, zcu104/linux-fpgamgr)
```

新バージョンがない場合（exit 1）:

```
$ fabricgate watch fabricgate/blink --since-version 1.1.0

No new version found for fabricgate/blink (latest: 1.1.0)
```

シェル更新の監視:

```
$ fabricgate watch --shell community/zcu104-shell --since-version 1.2.0

New shell version found: community/zcu104-shell:1.3.0
```

**CI パイプライン使用例（GitHub Actions）:**

```yaml
- name: Check for new shell
  run: fabricgate watch --shell community/zcu104-shell --since-version $CURRENT_SHELL_VERSION
  continue-on-error: true
  id: check_shell

- name: Rebuild if new shell available
  if: steps.check_shell.outcome == 'success'
  run: make build
```

**Exit codes:**
- 0: 新バージョンが存在する（条件を満たす更新あり）
- 1: 新バージョンが存在しない / デザインが見つからない
- 2: Permission（private/access-controlled な namespace・design への 401 / 403）
- 3: 不正な design-ref / `--since-version`（または `<design-ref>` と `--shell` の同時・無指定）
- 4: ネットワークエラー

> V1 実装: Read API のポーリングのみ。WebSocket / Server-Sent Events は V2 以降で検討。

---

### 3.9 `fabricgate webhook`
> **Not available yet.** The hosted registry does not implement these endpoints, so this
> command group is hidden from `--help` and any call returns 404. Tracked in
> [issue #6](https://github.com/harurun78/fabricgate/issues/6).


Webhook（HTTP 通知）の管理コマンド。ネームスペース管理者が利用する。

```
fabricgate webhook <subcommand>
```

#### サブコマンド一覧

| Subcommand | Description |
|---|---|
| `fabricgate webhook create` | Webhook を作成する |
| `fabricgate webhook list` | Webhook 一覧を表示する |
| `fabricgate webhook delete` | Webhook を削除する |
| `fabricgate webhook test` | テスト配信を送信する |
| `fabricgate webhook deliveries` | デリバリーログを表示する |

---

#### `fabricgate webhook create`

```
fabricgate webhook create --namespace <ns> --url <url> --events <event,...> [--design <design>]
```

**Options:**

| Option | Required | Description |
|---|:---:|---|
| `--namespace` | ✓ | 対象ネームスペース |
| `--url` | ✓ | 通知先 URL（HTTPS 必須） |
| `--events` | ✓ | カンマ区切りイベント種別 |
| `--design` | — | 特定 design のみ購読する場合に指定 |

**Behavior:**

```
$ fabricgate webhook create --namespace alice --url https://ci.example.com/hooks/fg \
    --events design.version.published,design.version.yanked

Webhook created (id: 1)
  URL:     https://ci.example.com/hooks/fg
  Events:  design.version.published, design.version.yanked
  Design:  (all designs in namespace alice)

  Secret: whsec_Abc123...

  ⚠  この secret は一度だけ表示されます。安全な場所に保管してください。
     受信側で X-FabricGate-Signature-256 ヘッダーを検証してください。
```

**Exit codes:**
- 0: Success
- 2: Authentication / permission error (未認証 / 401 / 403)
- 3: Invalid URL (not HTTPS) / webhook limit exceeded
- 4: Network error / server 5xx

---

#### `fabricgate webhook list`

```
fabricgate webhook list --namespace <ns> [--json]
```

**Behavior:**

```
$ fabricgate webhook list --namespace alice

ID   URL                                  EVENTS                        STATUS   LAST DELIVERED
1    https://ci.example.com/hooks/fg      design.version.published +1   active   2026-03-27
2    https://hooks.slack.com/...          design.version.published      failing  2026-03-25
```

---

#### `fabricgate webhook delete`

```
fabricgate webhook delete --namespace <ns> <id>
```

**Behavior:**

```
$ fabricgate webhook delete --namespace alice 1

Delete webhook 1 (https://ci.example.com/hooks/fg)? [y/N] y
Deleted.
```

**Options:**
- `--force`: 確認プロンプトをスキップ

---

#### `fabricgate webhook test`

```
fabricgate webhook test --namespace <ns> <id>
```

**Behavior:**

```
$ fabricgate webhook test --namespace alice 1

Sending test delivery to https://ci.example.com/hooks/fg ...
  Status: 200 OK  (142ms)  ✓
```

---

#### `fabricgate webhook deliveries`

```
fabricgate webhook deliveries --namespace <ns> <id> [--limit <n>]
```

**Behavior:**

```
$ fabricgate webhook deliveries --namespace alice 1

DELIVERY ID       EVENT                          STATUS   DURATION   DELIVERED AT
evt_01HZ9X...     design.version.published       200      142ms      2026-03-27 10:00
evt_01HZ8Y...     design.version.yanked          200       98ms      2026-03-26 15:30
evt_01HZ7Z...     design.version.published       500      ---        2026-03-25 09:12  (retry pending)
```

---

### 3.10 `fabricgate stats`

Design / Namespace のダウンロード統計を表示するコマンド。

```
fabricgate stats <design-ref|--namespace <ns>> [options]
```

#### `fabricgate stats <design-ref>`

Design の統計を表示する。

```
fabricgate stats <design-ref> [--period <daily|weekly|monthly>] [--from <date>] [--to <date>] [--version <version>]
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `--period` | `daily` | 集計粒度 (`daily` / `weekly` / `monthly`) |
| `--from` | 30 日前 | 集計開始日 (ISO 8601) |
| `--to` | today | 集計終了日 (ISO 8601) |
| `--version` | — | 特定バージョンに絞り込む |

**Behavior:**

```
$ fabricgate stats alice/fpga-uart

alice/fpga-uart  (total: 4,821 downloads)

Daily downloads — last 30 days
  2026-03-25  ████████████████████████████  42
  2026-03-26  ███████████████████████████████████████  67
  2026-03-27  ████████████████████████████████  55
  ...

  Last 7d:   384    Last 30d: 1,621
```

```
$ fabricgate stats alice/fpga-uart --version 1.2.0

alice/fpga-uart:1.2.0  (total: 1,203 downloads)

Daily downloads — last 30 days
  2026-03-25  ████████████  15
  ...
```

#### `fabricgate stats --namespace <ns>`

Namespace の統計サマリーを表示する。

```
fabricgate stats --namespace <ns>
```

**Behavior:**

```
$ fabricgate stats --namespace alice

Namespace: alice  (total: 12,480 downloads)

Top designs:
  1. alice/fpga-uart    4,821
  2. alice/axi-bridge   3,902
  3. alice/blink        2,109

  Last 7d:   384    Last 30d: 1,621
```

**Exit codes:**
- 0: Success
- 1: Design / Namespace not found
- 2: Permission error (private namespace without auth)
- 3: Invalid date range (`--from` > `--to` 等の不正な引数)
- 4: Network error / server 5xx

> 注: `<design-ref>` と `--namespace` の同時指定・無指定など引数の使い方の誤りは Click の usage error（exit 2）になる。これは終了コード標準（意味論カテゴリ）とは別レイヤーの引数エラーである。

---

### 3.11 `fabricgate quota`

Namespace のストレージ使用状況を表示するコマンド。

```
fabricgate quota [--namespace <ns>]
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `--namespace` | ログイン中ユーザーのデフォルト namespace | 対象 namespace |

**Behavior:**

```
$ fabricgate quota --namespace alice

Namespace: alice

  Storage    1.0 GB / 5.0 GB   [████████░░░░░░░░░░░░░░░░░░░░░░]  20%
  Designs        12 / 200
  Versions / design limit: 100
  Max file size: 500 MB
```

**警告表示（80% 超過時）:**

```
$ fabricgate quota --namespace alice

Namespace: alice

  Storage    4.4 GB / 5.0 GB   [████████████████████████████░░]  88%  ⚠ 上限に近づいています
  Designs        12 / 200
```

`fabricgate push` 実行時もクォータ上限の 80% を超えている場合は同様の警告を表示する（アップロードは継続）。

**Exit codes:**
- 0: Success
- 1: Namespace not found
- 2: Permission error（private namespace への 401 / 403）
- 3: Invalid namespace（不正な namespace 形式）
- 4: Network error / server 5xx

---

### 3.12 `fabricgate yank`

バージョンを yank（ソフト削除）する。`ns:{namespace}:admin` 権限が必要。

```
fabricgate yank <design-ref> [<version>...] [--reason <text>]
```

**Arguments:**
- `<design-ref>`: `namespace/design:version`（単一バージョン）または `namespace/design`（`<version>...` と組み合わせ）
- `<version>...`: yank するバージョンを複数指定（最大 50）

**Options:**

| Option | Description |
|---|---|
| `--reason` | yank の理由（任意） |

**Behavior:**

```
$ fabricgate yank community/fft-accel:1.0.0 --reason "Known timing issue"

Yanking community/fft-accel:1.0.0 ...
  ✓ yanked  community/fft-accel:1.0.0
  Reason: Known timing issue

$ fabricgate yank community/fft-accel 0.9.0 1.0.0 --reason "CVE-2026-0001"

Yanking 2 versions of community/fft-accel ...
  ✓ yanked  community/fft-accel:0.9.0
  ✓ yanked  community/fft-accel:1.0.0
  Reason: CVE-2026-0001
```

**Exit codes:**
- 0: Success
- 1: Design / version not found
- 2: Permission error（未認証 / 401 / 403）
- 3: Invalid（不正な design-ref / semver、バージョン未指定、50 バージョン超）
- 4: Network error / server 5xx

---

### 3.13 `fabricgate deprecate`

バージョンを deprecated（非推奨）状態に設定・解除する。

```
fabricgate deprecate <design-ref> [<version>...] --message <text> [--successor <design-ref>]
fabricgate deprecate --undo <design-ref> [<version>...]
```

**Behavior:**

```
$ fabricgate deprecate community/fft-accel:1.0.0 \
    --message "Upgrade to 2.0.0" \
    --successor community/fft-accel:2.0.0

Deprecating community/fft-accel:1.0.0 ...
  ✓ deprecated  community/fft-accel:1.0.0
  Message: Upgrade to 2.0.0
  Successor: community/fft-accel:2.0.0

$ fabricgate deprecate --undo community/fft-accel:1.0.0

Undeprecating community/fft-accel:1.0.0 ...
  ✓ undeprecated  community/fft-accel:1.0.0
```

**Exit codes:**
- 0: Success
- 1: Design / version not found
- 2: Permission error（未認証 / 401 / 403）
- 3: Invalid（`--message` 必須、不正な design-ref / semver、50 バージョン超）
- 4: Network error / server 5xx

---

### 3.14 `fabricgate license-check`

Design の `tool_requirements` メタデータを表示し、指定ツール・エディションでの利用可否を確認する。

> **注意:** FabricGate はツール要件情報の表示のみを行う。実際のライセンス準拠はパブリッシャーおよびユーザーの責任。

```
fabricgate license-check <design-ref> [--tool <tool-id>] [--edition <edition>]
```

**Arguments:**
- `<design-ref>`: `namespace/design:version`

**Options:**

| Option | Description |
|---|---|
| `--tool` | チェック対象ツール識別子（例: `vivado`, `f4pga`）。複数回指定可能 |
| `--edition` | エディション（`standard`, `enterprise`, `pro`, `lite`）。`--tool` と組み合わせて使用 |
| `--json` | JSON 形式で出力 |

**Behavior (ツール指定なし — `tool_requirements` 一覧表示):**

```
$ fabricgate license-check community/fft-accel:1.0.0

Design:   community/fft-accel:1.0.0
Type:     partial (Partial Reconfiguration)

Tool Requirements:
  vivado (required)
    Min version: 2024.1
    Edition:     standard
    Note:        DFX flow (Partial Reconfiguration)

  f4pga (optional)
    Note:        open source alternative (PR support in progress)

Disclaimer: License compliance is the publisher's and user's responsibility.
```

**Behavior (ツール・エディション指定あり):**

```
$ fabricgate license-check community/fft-accel:1.0.0 --tool vivado --edition standard

Design:   community/fft-accel:1.0.0

check: vivado (standard)
  ✓  vivado standard >= 2024.1 satisfies required tool
  ✓  DFX feature available in Vivado Standard edition

Result: MEETS REQUIREMENTS

Disclaimer: License compliance is the publisher's and user's responsibility.
```

**`--json` 出力:**

```json
{
  "design": "community/fft-accel",
  "version": "1.0.0",
  "bitstream_type": "partial",
  "tool_requirements": [
    {
      "tool": "vivado",
      "min_version": "2024.1",
      "edition": "standard",
      "required": true,
      "note": "DFX flow (Partial Reconfiguration)"
    },
    {
      "tool": "f4pga",
      "required": false,
      "note": "open source alternative (PR support in progress)"
    }
  ],
  "check": {
    "tool": "vivado",
    "edition": "standard",
    "meets_requirements": true,
    "notes": [
      "vivado standard >= 2024.1 satisfies required tool",
      "DFX feature available in Vivado Standard edition"
    ]
  },
  "disclaimer": "FabricGate provides toolchain metadata only. License compliance is the publisher's and user's responsibility."
}
```

**Exit codes:**
- 0: Success (要件を満たす、または `--tool`/`--edition` 未指定で一覧表示のみ)
- 1: Design / version not found / `tool_requirements` が空（チェック対象なし）
- 2: Permission（private/access-controlled な namespace・design への 401 / 403）
- 3: DOES NOT MEET REQUIREMENTS (`--tool` / `--edition` 指定時のみ)
- 4: Network error / server 5xx

> 注: 「`tool_requirements` が空」は以前 exit 2 だったが、意味論標準で 2 は Permission に予約されたため 1（generic）へ正規化した（ADR-008）。

---

## 4. Local Cache Structure

```
~/.fabricgate/
  credentials.json              # Auth token fallback (0600, no keychain env only)
  cache/                        # OS keychain が優先。keychain 不可環境のみファイル使用
    fabricgate/
      blink/
        1.0.0/
          index.yaml            # Cached Design Index
          xczu7ev-pynq/
            manifest.yaml       # Platform Manifest
            blink.bit
            blink.hwh
          xczu7ev-linux-fpgamgr/
            manifest.yaml
            blink.bit
            blink.dtbo
```

## 5. 3層アーキテクチャ

CLI / SDK は以下の3層で構成する。将来的にコアロジックの他言語実装、SDK 提供言語の追加、CLI 配布方式の変更に対応するための設計。

```
┌──────────────┐   ┌──────────────┐
│  CLI (Click) │   │  SDK (Python) │   ...将来: SDK (Rust), SDK (Go)
│  fabricgate pull ... │   │  fg.pull()    │
└──────┬───────┘   └──────┬────────┘
       │                  │
  ユーザー入力の解釈        Python API の型付け
  出力整形 (rich)          戻り値の構造化
       │                  │
       ▼                  ▼
┌─────────────────────────────┐
│         Client Logic        │   ...将来: Rust で再実装も可
│  fabricgate.client          │
│                             │
│  RegistryClient  (HTTP通信)  │
│  CacheManager    (ローカル)   │
│  Validator       (SHA256検証) │
│  Resolver        (platform解決)│
│  Publisher       (push組立)   │
└─────────────────────────────┘
```

### 5.1 境界ルール

| ルール | 詳細 |
|---|---|
| **Client は CLI/SDK を知らない** | Click, rich への依存なし。戻り値は Pydantic モデルまたはプリミティブ |
| **Client は models に依存する** | `fabricgate.models` は共通基盤 |
| **CLI は Client を呼ぶだけ** | ビジネスロジックを持たない。入力パース → Client 呼び出し → 出力整形 |
| **SDK は Client を呼ぶだけ** | 薄いラッパー。型付け + docstring が主な仕事 |
| **Client の進捗通知はコールバック** | `on_progress: Callable` を Client に渡す。CLI は rich プログレスバー、SDK はユーザー定義 or None |

### 5.2 Client モジュール (`fabricgate.client`)

| モジュール | 責務 |
|---|---|
| `registry_client.py` | Registry API への HTTP 通信 (httpx)。全 API エンドポイントのメソッド |
| `cache.py` | ローカルキャッシュの読み書き。キャッシュヒット判定 |
| `validator.py` | SHA-256 ダイジェスト検証。Design Index ↔ Platform Manifest ↔ Artifact の整合性チェック |
| `resolver.py` | プラットフォーム解決ロジック。Design Index から platform を選択 |
| `publisher.py` | push 用のパッケージ組立。ディレクトリ走査 → バリデーション → multipart 構築 |
| `auth.py` | 認証情報の読み書き (`~/.fabricgate/credentials.json`) |
| `config.py` | 設定ファイルの読み込み (`~/.fabricgate/config.yaml`) + 環境変数マージ |

**依存関係:** Client → models, httpx, pyyaml, pydantic-settings
**依存しない:** Click, rich, FastAPI, SQLAlchemy

### 5.3 CLI ラッパー (`fabricgate.cli`)

```python
# cli/commands/pull.py の概要
import click
from rich.progress import Progress
from fabricgate.client.registry_client import RegistryClient
from fabricgate.client.cache import CacheManager
from fabricgate.client.resolver import resolve_platform

@click.command()
@click.argument("design_ref")
@click.option("--platform", default=None)
def pull(design_ref: str, platform: str | None) -> None:
    client = RegistryClient(registry_url=...)
    cache = CacheManager(cache_dir=...)

    # Client を呼ぶ
    index = client.get_design_index(design_ref)
    selected = resolve_platform(index, platform)

    # 進捗表示は CLI の責務
    with Progress() as progress:
        result = client.download_artifacts(
            ...,
            on_progress=lambda current, total: progress.update(...),
        )

    cache.store(result)
    click.echo(f"Saved to {result.path}")
```

**役割:** 入力パース (Click) → Client 呼び出し → 出力整形 (rich)。ロジックなし。

### 5.4 SDK ラッパー (`fabricgate.sdk`)

```python
# sdk/api.py
from fabricgate.client.registry_client import RegistryClient
from fabricgate.client.cache import CacheManager
from fabricgate.client.resolver import resolve_platform
from fabricgate.models.cli import PullResult, DesignInfo, SearchResult

def pull(
    design_ref: str,
    *,
    platform: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    cache_dir: str = "~/.fabricgate/cache",
    on_progress: Callable[[int, int], None] | None = None,
) -> PullResult:
    """Download a design for a specific platform.

    Args:
        design_ref: Design reference (e.g., "fabricgate/blink:1.0.0")
        platform: Target platform (e.g., "zcu104/pynq")
        registry: Registry base URL
        cache_dir: Local cache directory
        on_progress: Optional progress callback (current_bytes, total_bytes)

    Returns:
        PullResult with local path, artifact list, cache hit status
    """
    client = RegistryClient(registry_url=registry)
    cache = CacheManager(cache_dir=cache_dir)
    index = client.get_design_index(design_ref)
    selected = resolve_platform(index, platform)
    result = client.download_artifacts(..., on_progress=on_progress)
    cache.store(result)
    return result
```

**役割:** デフォルト値設定 + 型保証 + docstring。Client と同じ引数構成だが、ユーザーフレンドリーなインターフェースを提供。

### 5.5 使用例

```python
import fabricgate

# Pull (returns PullResult with local path)
result = fabricgate.pull("fabricgate/blink:1.0.0", platform="zcu104/pynq")
print(result.path)       # ./blink-1.0.0/
print(result.artifacts)  # ['blink.bit', 'blink.hwh']

# Search
results = fabricgate.search("dma", platform="zcu104/pynq")
for r in results:
    print(f"{r.name}:{r.version} — {r.summary}")

# Info
info = fabricgate.info("fabricgate/blink:1.0.0")
print(info.platforms)  # ['zcu104/pynq', 'zcu104/linux-fpgamgr']

# Verify
ok = fabricgate.verify("./blink-1.0.0/")
assert ok

# PYNQ integration
from pynq import Overlay
result = fabricgate.pull("xilinx/axi-dma-demo:2.0.1", platform="zcu104/pynq")
ol = Overlay(f"{result.path}/design.bit")
```

## 6. Implementation Notes

### 6.1 Tech Stack

- **Language**: Python ≥ 3.11
- **CLI framework**: Click (CLI ラッパーのみ)
- **HTTP client**: httpx (Core 内 RegistryClient)
- **Progress/Output**: rich (CLI ラッパーのみ)
- **Package**: `fabricgate` on PyPI
- **Entry point**: `fabricgate` console script (alias: `fgate`)

### 6.2 Config File

`~/.fabricgate/config.yaml` (optional):

```yaml
registry: https://registry.fabricgate.dev/api/v1
platform: zcu104/pynq           # default platform
cache_dir: ~/.fabricgate/cache
```
