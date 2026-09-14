# Client Behavior & Wire Conventions

Version: 1.0.0-draft
Date: 2026-06-28
Parent: [registry-api.md](./registry-api.md)

---

## 1. 概要

本書は、新しい言語の SDK が fabricgate クライアントを**忠実に再実装**するための、言語中立な仕様である。対象は 2 つ:

- **Wire 契約** — registry と相互運用するために守らねばならない規約（multipart 命名・content-type・digest 形式・push/pull のワイヤ）。
- **Client 挙動** — 一貫した UX のためにクライアントが行うべき処理（platform/version 解決・依存解決と順序・shell 自動取得・検証）。

データ形状は G1 の JSON Schema（[`docs/contracts/schemas/`](../contracts/schemas/)）を、HTTP endpoint は [registry-api.md](./registry-api.md) を正とする。本書はそれらに跨る規約と、従来コードにのみ存在した未文書アルゴリズムの **canonical**（正本）であり、挙動・規約が他文書と矛盾する場合は本書を優先する。

各規定には現実装の `file:line` を参考として併記する（保守時の追跡用。`src/fabricgate/` 配下）。

### 1.1 規範レベル（RFC-2119）

キーワード **MUST / MUST NOT / SHOULD / SHOULD NOT / MAY** は [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) に従う。各節に規範レベルを付す:

| レベル | 対象 | 意味 |
|--------|------|------|
| **MUST（wire 契約）** | §2 識別子, §3 push wire, §7.1 semver 構文 | registry が強制。相互運用に必須 |
| **SHOULD（client 挙動）** | §6 platform 解決, §7.2 version 選択, §8 依存, §9 shell, §10 検証 | cross-SDK 一貫性。等価 UX に必要 |
| **参考（非規範）** | §5 サーバ内部, §11 cache, §12 出力 | SDK は独自実装してよい |

---

## 2. アドレッシングと識別子（MUST）

### 2.1 Design 参照

デザインは `namespace/design:version` で参照する（例: `fabricgate/blink:1.0.0`）。`:version` は**厳密な semver** であり、エイリアス（`latest` 等）は wire レベルでは定義しない（「最新」選択は §7.2 を参照）。

### 2.2 識別子フォーマット

| 識別子 | 正規表現 / 形式 | 出典 |
|--------|----------------|------|
| `SemVer` | `^(0\|[1-9]\d*)\.(0\|[1-9]\d*)\.(0\|[1-9]\d*)$` | `models/common.py` |
| `DesignName` | `namespace/design`（各セグメントは小文字英数とハイフン等） | `models/common.py` |
| `PlatformId` | `{board_id}/{runtime}`（例 `zcu104/pynq`） | `models/common.py` |
| `NamespaceName` | 小文字英数で始まり、英数・ハイフン | `models/common.py` |

各識別子の厳密な制約は G1 schema（`design-index.schema.json` 等）の `$defs` を正とする。

### 2.3 Digest 形式

コンテンツダイジェストは **`sha256:<64 桁小文字 hex>`**（正規表現 `^sha256:[0-9a-f]{64}$`、`models/common.py` `SHA256Digest`）。

> **注意**: multipart のアーティファクト検証フィールド（§3）およびクライアント/サーバの digest 照合（§10）では、`sha256:` プレフィックスを除いた **hex 部分のみ**を用いる場面がある。Design Index / Manifest 内の `digest` フィールドは `sha256:` 付きの完全形を用いる。

---

## 3. Push Wire（multipart/form-data）（MUST）

`fabricgate push` は 1 バージョンを 1 つの `multipart/form-data` リクエストでアップロードする。フィールド名は以下の規約に従わねばならない（`client/publisher.py:60-127`、サーバ分類は `registry/upload_validation.py:62-76` `classify_part`）。

### 3.1 フィールド命名

| フィールド名 | 内容 | 必須 |
|--------------|------|------|
| `index` | Design Index（YAML または JSON） | 必須 |
| `readme` | README（Markdown） | 任意 |
| `platform:{board_id}/{runtime}:manifest` | その platform の Platform Manifest | platform ごとに必須 |
| `platform:{board_id}/{runtime}:artifact:{filename}` | manifest が参照するアーティファクト本体 | アーティファクトごと |

`{board_id}/{runtime}` は `PlatformId`、`{filename}` は manifest の `artifacts[].file`。分類規則: `index` / `readme` は完全一致、manifest は `platform:` で始まり `:manifest` で終わる、artifact は `platform:` で始まり `:artifact:` を含む。それ以外は `unknown`（無視される）。

### 3.2 Content-Type 許可リスト（`upload_validation.py:18-21`）

| カテゴリ | 許可 content-type |
|----------|-------------------|
| index / manifest | `application/x-yaml`, `application/json`, `text/yaml` |
| readme | `text/markdown`, `text/plain` |
| artifact | `application/octet-stream`（欠落時は octet-stream 扱い） |

> index と manifest は別定数（`ALLOWED_INDEX_TYPES` / `ALLOWED_MANIFEST_TYPES`）だが現在は同値。

### 3.3 サイズ上限（`upload_validation.py:10-13`）

| 制限 | 値 |
|------|----|
| アーティファクト 1 件 | 256 MB |
| README | 1 MB |
| リクエスト総量 | 512 MB |
| パート数 | 64 |

### 3.4 サーバ側検証

サーバは各アーティファクトの本体 bytes の SHA-256（hex）を計算し、対応する manifest の `sha256` フィールドと照合する。不一致はアップロードを拒否する（`registry/routers/designs/versions.py:325-333`）。サーバは `form.multi_items()` を走査し、各パートを分類して処理する（最初の一致を採用）。

---

## 4. Pull Wire（MUST）

クライアントは **registry HTTP API 経由**でバージョン詳細・Platform Manifest・アーティファクトを取得する（endpoint は [registry-api.md](./registry-api.md) を正とする）。

- アーティファクト本体は **API またはサーバが発行する presigned URL 経由**で取得する。
- **クライアントはサーバのオブジェクトストレージキーを構築してはならない（MUST NOT）。** サーバのキー構成は内部実装（§5）であり、SDK の関与対象外である。

---

## 5. サーバ内 content addressing（内部・非規範）

> この節は registry の内部実装であり、**SDK は関与しない**（pull は §4 の API 経由）。todo にある「CAS キー」はこのサーバ側キーを指し、§11 のローカルキャッシュ layout とは**別物**である点に注意。

registry はアーティファクトをコンテンツアドレスで保存する。S3 オブジェクトキーは `cas/{sha256[:2]}/{sha256}/{filename}`（`registry/services/artifact_service.py:11-27` `make_artifact_s3_key`。`sha256` は 64 桁 hex、`filename` にパス区切りを含めない）。同一内容（同一 SHA-256）は同一キー＝一度だけ保存される（dedup）。Manifest は `manifests/{ns}/{design}/{ver}/{board_id}/{runtime}/manifest.json`（`registry/services/dependency_service.py:89-90`）に保存される（CAS ではない）。

---

## 6. Platform 解決（SHOULD）

Design Index の `platforms[]` から対象 platform を選ぶ（`client/resolver.py` `resolve_platform` / `resolve_platform_detailed`）:

1. `--platform`（または `FG_PLATFORM`）が指定されている場合 → **2 段解決**を行う:
   1. **完全一致**（最優先）: `entry.platform` と完全一致するものがあればそれを選ぶ。挙動は従来どおり不変。
   2. **ファミリフォールバック**（miss 時のみ）: 指定が `board_id/runtime` 形式で `board_id` が `generic-` で始まらない場合、Board DB（`board-db-schema.md`）で `board_id → device_family` を引き、`generic-{device_family}/{runtime}` と完全一致する entry を再探索する。ヒットすれば選択し、**由来（元の指定 platform）を利用者へ明示する**（CLI 表示は `cli-specification.md` §3.1 参照）。Board DB に無い board_id はフォールバックせず 3. へ。
   3. それでも一致が無ければエラー（利用可能 platform 一覧付き）。
2. 指定が無く、`platforms` が **1 件のみ**の場合 → その 1 件を自動選択する（フォールバック非適用・不変）。
3. 指定が無く、**複数**ある場合 → エラー（曖昧）。CLI は候補一覧を提示し、`--platform` または `FG_PLATFORM` を要求する（`cli-specification.md` 参照）。

ファミリフォールバックは**加算的変更**である: 完全一致が存在するケースの挙動は不変で、従来エラーだったケースの一部（Board DB 登録済み実ボード指定 × `generic-{device_family}` entry あり）を成功に変えるのみ。解決不能時の失敗分類（exit code）も従来どおり不変（`UNRESOLVABLE` 系）。設計判断の経緯は 本節 を参照。

---

## 7. Version / Semver 解決

### 7.1 制約構文（MUST）

依存の version 制約は次の構文で表される（`client`/`registry` 双方が同一に解釈せねばならない。`registry/services/dependency_service.py:49-81` `match_version_constraint`）:

| 構文 | 意味 |
|------|------|
| `*` | 任意のバージョン |
| `^X.Y.Z` | 同一 major、かつ `≥ X.Y.Z` |
| `~X.Y.Z` | 同一 major.minor、かつ `≥ X.Y.Z` |
| `X.Y.Z` | 厳密一致 |

> `^0.y.z` は同一 major（= 0）であれば許可する簡易仕様であり、npm/Cargo の `^0.y.z`（同一 minor に限定）とは**意図的に異なる**（`dependency_service.py:67-71` のコメント参照）。

### 7.2 最良バージョン選択（SHOULD）

制約集合に対する「最良」バージョンは、**yank されていない**候補のうち、全制約を満たし、かつ semver を数値タプルとして**降順**で最も高いものとする（`dependency_service.py:116-135` `resolve_best_version`。満たすものが無ければ解決失敗）。

### 7.3 「最新」の選択（SHOULD）

`namespace/design:version` の `:version` は厳密指定であり、wire レベルに `latest` エイリアスは無い。クライアントが「最新版」を提示する場合は、API で全バージョンを取得し、§7.2 と同じ規則（yank 除外・semver 降順最高）で選ぶべきである。

---

## 8. 依存解決と Topological 順序（SHOULD）

Platform Manifest の `dependencies[]`（および partial の shell、§9）を再帰的に解決する。サーバは `GET .../platforms/{board_id}/{runtime}/dependencies?include_optional={bool}` で**解決済みの平坦リスト**を返す（`registry/routers/designs/platforms.py:293-330`、アルゴリズムは `dependency_service.py:143-323`）。

クライアントの責務:

- サーバが返す依存リストは**topological 順（依存が依存元より先）**に整列済みである。クライアントはこの順に**逐次ダウンロードすべき**であり、独自の topological sort は不要（逐次 DL ループ `client/puller.py:122-167`、呼び出し元 `:327-339`）。
- 各依存は `target/deps/{namespace}-{design}-{version}/` に展開する（`puller.py:122-167`）。

サーバ側解決の保証（再実装の参考）:

- 再帰 DFS ＋ 制約累積。同一デザインを複数経路で参照した場合は制約を合流（diamond）。制約強化で最良バージョンが変われば再解決する（`dependency_service.py:234-255`）。
- **循環依存**は検出時に `CIRCULAR_DEPENDENCY` エラー（`dependency_service.py:256-262`）。
- 上限: 深さ **10**、総ノード **200**（超過はエラー）。

---

## 9. Shell 自動取得（SHOULD）

partial bitstream には静的 shell が必要であり、クライアントは shell を自動取得すべきである（`client/puller.py:170-238`）。リファレンス実装は shell endpoint（`client.get_shell`）を呼び、registry が partial デザインには shell を返し、partial でない / full bitstream には `404` または `422`（`NOT_A_PARTIAL`）を返す → クライアントは no-op として扱う（クライアント側で `bitstream_type` を判定せず、サーバが gate する）:

- shell は `target/shell/{shell_dirname}/` に展開する。
- `--no-shell` が指定された場合はスキップする（partial を shell 無しで取得）。
- shell のアーティファクトも §10 の digest 検証の対象。

shell 依存の宣言形式（`name`/`version`/`board_id`/`runtime` 等）は [platform-manifest-schema.md](./platform-manifest-schema.md) と `platform-manifest.schema.json` を正とする。

---

## 10. 検証（SHOULD: digest / MAY: attestation）

### 10.1 Digest 検証（SHOULD、既定 on）

各アーティファクトをダウンロードした後、その SHA-256（hex）を対応する manifest の `sha256` と照合せねばならない。不一致は整合性エラー（`IntegrityError`）として中断すべきである（`client/validator.py:23-25` `verify_artifact`〔hex 比較〕、`client/puller.py:312-324`）。なお `verify_digest`（`validator.py:28-30`）は `sha256:` 付き完全形を扱う別関数である（§2.3 の 2 形式の区別に対応）。root・依存・shell の全アーティファクトに適用する。既定で有効（opt-out 可）。

### 10.2 Attestation 検証（MAY、opt-in）

署名検証は任意機能である（`--verify-attestation`、`client/puller.py:241-259`）:

- 各アーティファクトに対し `cosign verify-blob` を実行する。`cosign` バイナリが PATH に必要。
- 鍵 / 証明書 ID / OIDC issuer 等のパラメータ指定は**未実装**（現状は素の `cosign verify-blob`）。
- Manifest の `attestation` フィールド（`bundle` / `transparency_log_url`、`models/platform_manifest.py:106-115`）は**準備段階**であり、現行 pull フローでは未使用。将来の拡張点。

---

## 11. ローカルキャッシュ layout（参考・非規範）

> SDK は独自のキャッシュ実装を採ってよい。以下は fabricgate リファレンスクライアントの実装（`client/cache.py`）。

- ルート: `~/.fabricgate/cache/`。
- インデックス: `index.json`（`CacheIndex` = `CacheEntry[]`。各 entry: `name` / `version` / `platform` / `path` / `pulled_at` / `digest`。`models/cli.py:51-65`）。
- platform ディレクトリ: `{cache}/{namespace}/{design}/{version}/{device}/{runtime}/`（**人間可読**であり、§5 のサーバ CAS とは異なる）。
- lookup は `(name, version, platform)` 一致かつディスク上にパスが存在する場合にヒット（`cache.py:45-57`）。

---

## 12. Pull 出力レイアウト（参考・非規範）

`fabricgate pull` の出力ディレクトリ構成（リファレンス実装）:

```
target/
  <root artifacts>
  deps/
    {namespace}-{design}-{version}/   # 依存ごと
  shell/
    {shell_dirname}/                  # partial の shell（§9）
```

SDK は独自の配置を採ってよい。

---

## 13. 既知の制約

Design Index・各 Platform Manifest・Board DB ファイルの **top-level（最上位）オブジェクトは未知キーを拒否しない**（公開 JSON Schema に `additionalProperties` を設定していない＝Pydantic モデルの `extra="ignore"` を忠実に反映）。したがって SDK は、これらの**最上位**で未知キー（typo 等）が検証エラーになると**仮定してはならない（MUST NOT）**。一方、ネストされたサブモデル（`PlatformEntry`・`ArtifactRef` 等）は strict（未知キー拒否）である。G1（[wire 形式 JSON Schema](../contracts/schemas/)）由来の性質。

---

## 14. Client API boundary（in-Python 契約）

pull/push のオーケストレーション（`client/puller.py`、`sdk/designs/push.py`）が依存する
client メソッドの最小契約は `typing.Protocol` の **`RegistryClientProtocol`**
（`client/registry_client.py`）として定義される。`pull_design` 等のシームはこの Protocol 型で
client を受けるため、適合する任意実装（テスト fake、将来の native/PyO3 client）が drop-in できる。

契約メソッド（シグネチャは `RegistryClient` と一致）: `get_version` / `get_dependencies` /
`get_shell` / `get_platform_manifest_bytes` / `download_artifact` /
**`create_artifact_uploads` / `upload_artifact`** / `publish_version` /
`get_namespace_quota`。実装は HTTP エラー時に `RegistryError`、transport 失敗時に
`NetworkError` を §10 / §3 のフィールド契約どおりに raise しなければならない（MUST）。

> **`create_artifact_uploads` / `upload_artifact` は 2026-09-03 に追加**。push は
> アーティファクトを registry API ではなくオブジェクトストレージへ直接 PUT する
> （Cloud Run が 32MiB でリクエストを打ち切るため。[registry-api.md](./registry-api.md)
> §`/uploads`）。`upload_artifact` はレジストリではなくストレージへの HTTP なので、
> エラーは XML であり、実装はそれを `NetworkError` に翻訳する（MUST）。
> ticket の `url` が `None` のときは**アップロードしない**（内容が保存済みという意味）。

> これは in-Python の境界型であり、registry HTTP API そのものの契約は [registry-api.md](./registry-api.md)、
> データ形状は G1 schema を正とする。`RegistryClient` の適合は CI（`mypy src` の静的表明＋
> `tests/unit/test_client_protocol.py`）で担保される。

---

## 15. Error kinds (client API boundary)

A client failure carries a language-neutral **failure kind** distilled from the
registry's HTTP status and wire error code. This classification is owned by the
core (`client/errors.py::FailureKind`, exposed as `RegistryError.kind`) so every
binding reads the same result rather than re-deriving it.

| kind | trigger |
|---|---|
| `PERMISSION` | HTTP 401 / 403 |
| `NOT_FOUND` | HTTP 404 |
| `UNRESOLVABLE` | HTTP 409 + wire code `DEPENDENCY_UNRESOLVABLE` |
| `SHELL_NOT_FOUND` | HTTP 409 + wire code `SHELL_NOT_FOUND` |
| `INVALID` | HTTP 409 (other) / 400 / 422 / 429 |
| `INFRA` | HTTP ≥ 500, or transport failure (`NetworkError`) |
| `GENERIC` | anything else |

A native reimplementation MUST classify identically. The terminal exit-code
mapping (kind → integer) is a CLI concern (ADR-008), not part of this contract.

---

## 16. 参考

- [registry-api.md](./registry-api.md) — HTTP endpoint・multipart 詳細
- [cli-specification.md](./cli-specification.md) — CLI UX・exit code
- [data-models.md](./data-models.md) — Pydantic モデル定義
- [design-index-schema.md](./design-index-schema.md) / [platform-manifest-schema.md](./platform-manifest-schema.md) / [board-db-schema.md](./board-db-schema.md)
- G1 機械可読スキーマ: [`docs/contracts/schemas/`](../contracts/schemas/)
- 実装出典: `client/{resolver,puller,cache,publisher,validator}.py`、`registry/services/{artifact_service,dependency_service}.py`、`registry/{upload_validation,routers/designs/versions}.py`、`models/common.py`
