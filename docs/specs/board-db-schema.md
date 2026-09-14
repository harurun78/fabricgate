# Board DB Schema

> **Machine-readable schema:** [`docs/contracts/schemas/board-db.schema.json`](../contracts/schemas/board-db.schema.json) (generated SoT; this page is the human explanation).

## 1. 概要

Board DB は FabricGate が platform (`board_id/runtime`) の `board_id` を正規化するための参照データベース。
CLI にバンドルされる `official.yaml` とユーザーが管理する `custom.yaml` の2ファイル構成。

## 2. ファイルレイアウト

```
~/.fabricgate/
  board-db/
    official.yaml    # CLI バンドル（バージョン管理済み、手動編集不可）
    custom.yaml      # ユーザー管理（任意）
```

`official.yaml` は CLI パッケージに同梱し、CLI のアップデート時に更新される。
ネットワーク接続なしで利用可能。`custom.yaml` は存在しない場合はスキップする。

## 3. YAML スキーマ

```yaml
# fabricgate-boarddb/v1
version: fabricgate-boarddb/v1

boards:
  - board_id: <string>          # 必須: ケバブケース、小文字英数字+ハイフン
    display_name: <string>      # 必須: 表示用名称
    vendor: <string>            # 省略可: ベンダー名
    boardpart: <string>         # 省略可: Vivado Board Store の BOARDPART 文字列
    device: <string>            # 省略可: デバイスパート (generic-* は省略可)
    device_family: <string>     # 必須: デバイスファミリ (xczu7ev, xc7z020, rp2040 等)
    pynq_supported: <bool>      # 省略可: PYNQ がサポートするボードか (default: false)
    virtual: <bool>             # 省略可: 仮想ボードか (default: false)
    category: generic | custom  # 省略可: 仮想ボードのカテゴリ
    interfaces:                 # 省略可: V1 はデータ蓄積のみ
      - type: <string>          # インターフェース種別 (pmod, hdmi, uart, mipi-csi 等)
        direction: tx | rx | inout  # 省略可
        count: <int>            # 省略可 (default: 1)
        source: vivado-boardstore | manual | community  # 省略可 (default: manual)
```

### 3.1 board_id 命名規則

| カテゴリ | パターン | 例 |
|---|---|---|
| 実ボード | `{vendor}-{model}` または登録名称 | `zcu104`, `pynq-z2`, `pico-ice` |
| 仮想 (generic) | `generic-{device_family}` | `generic-xczu7ev`, `generic-xc7z020` |
| 仮想 (custom) | `custom-{device_family}-{package}` | `custom-xczu7ev-ffvc1156` |

`board_id` は正規表現 `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$` に準拠する（小文字英数字とハイフンのみ、先頭・末尾はハイフン不可）。

## 4. 実ボードの例

```yaml
version: fabricgate-boarddb/v1

boards:
  - board_id: zcu104
    display_name: Xilinx ZCU104 Evaluation Board
    vendor: xilinx
    boardpart: xilinx.com:zcu104:part0:1.1
    device: xczu7ev-ffvc1156-2-e
    device_family: xczu7ev
    pynq_supported: true
    interfaces:
      - type: pmod
        count: 2
        source: vivado-boardstore
      - type: hdmi
        direction: tx
        count: 1
        source: vivado-boardstore
      - type: uart
        direction: inout
        count: 1
        source: vivado-boardstore

  - board_id: pynq-z2
    display_name: TUL PYNQ-Z2
    vendor: tul
    boardpart: tul.com.tw:pynq-z2:part0:1.0
    device: xc7z020clg400-1
    device_family: xc7z020
    pynq_supported: true
    interfaces:
      - type: pmod
        count: 2
        source: vivado-boardstore
      - type: hdmi
        direction: tx
        count: 1
        source: vivado-boardstore
      - type: audio
        direction: inout
        count: 1
        source: vivado-boardstore

  - board_id: pico-ice
    display_name: pico-ice (iCE40 + RP2040)
    vendor: tinyvision
    device_family: ice40up5k
    pynq_supported: false
    interfaces: []
```

## 5. 仮想ボードの定義

仮想ボードは実際の物理ボードに対応しない抽象エントリ。`fabricgate build` が自動生成し、Board DB にない BOARDPART を持つデザインのプラットフォームとして使用される。

### 5.1 generic-{device_family}

AXI-only デザイン向け。特定の物理ボードに依存しない汎用プラットフォーム。

```yaml
  - board_id: generic-xczu7ev
    display_name: Generic xczu7ev (AXI-only)
    device_family: xczu7ev
    virtual: true
    category: generic
    interfaces: []   # AXI-only のためボード固有インターフェースなし
```

- `device`, `boardpart`, `vendor` は省略
- `interfaces` は空リスト（AXI バスのみ使用）
- `fabricgate search` で `--device xczu7ev` 指定時にマッチする

### 5.2 custom-{device_family}-{package}

Board DB に未登録のボード向け。BOARDPART から device_family と package を抽出して自動生成。

```yaml
  - board_id: custom-xczu7ev-ffvc1156
    display_name: Custom xczu7ev-ffvc1156 (unregistered board)
    device_family: xczu7ev
    virtual: true
    category: custom
    interfaces: []   # V1: ユーザーが手動で追記可能
```

- `boardpart` は省略（未登録のため不定）
- V1 では `interfaces` のマッチングロジックは実装しない（データ蓄積のみ）

## 6. 検索・解決ロジック

CLI が `board_id` を解決する順序:

1. `custom.yaml` を先に検索（ユーザー定義が優先）
2. `official.yaml` を検索
3. どちらにもない場合 → `fabricgate build` では仮想ボードを提案、`fabricgate pull/push` ではエラー

`BOARDPART` から `board_id` を解決する手順:

1. `official.yaml` + `custom.yaml` を走査し、`boardpart` フィールドが一致するエントリを返す
2. 一致なし → デバイスパートから `device_family` と `package` を抽出し、`custom-{device_family}-{package}` を構築
3. `device_family` も判定できない場合 → ユーザーに手動入力を要求

## 7. ガバナンス

### V1
- `official.yaml` は CLI のリリースと同梱（`fabricgate-cli` Python パッケージ内に静的ファイルとして含む）
- メンテナンスは FabricGate Project が管理
- ユーザーは `custom.yaml` でエントリを追加・上書き可能

### V2（将来）
- `official.yaml` の追加エントリは GitHub PR で受け付ける予定
- PR テンプレートに必須フィールドと Vivado Board Store 確認手順を記載
- `interfaces` の自動収集（Vivado Board Store の XML から変換）

## 8. auto-generation フロー（fabricgate build との連携）

```
.hwh BOARDPART
  │
  ├─ Board DB にある → board_id を採用
  │
  └─ Board DB にない
       │
       ├─ EXTERNALINTERFACES: AXI-only
       │    → generic-{device_family} を提案 [Y/n]
       │
       └─ board-specific IP あり
            → custom-{device_family}-{package} を生成
            → interfaces は空で出力（ユーザーが手動追記）
```

## 9. バリデーションルール

| Rule ID | 説明 |
|---|---|
| `BOARD_ID_FORMAT` | `board_id` が `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$` に準拠すること |
| `DEVICE_FAMILY_REQUIRED` | `device_family` が必須フィールドであること |
| `VIRTUAL_CATEGORY_REQUIRED` | `virtual: true` の場合 `category` が `generic` または `custom` であること |
| `GENERIC_NO_BOARDPART` | `category: generic` のエントリに `boardpart` を設定しないこと |
| `DUPLICATE_BOARD_ID` | 同一ファイル内で `board_id` の重複がないこと（`official.yaml` と `custom.yaml` 間の重複は `custom` 優先） |
| `BOARDPART_UNIQUE` | `boardpart` の値は Board DB 全体でユニークであること |
