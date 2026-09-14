# API Contract Changelog

## [Unreleased]

### Changed
- **BREAKING (Platform Manifest)**: runtime discriminator `micropynq` renamed to
  `nanopynq` (ADR-015). No alias or deprecation period; manifests declaring
  `runtime: micropynq` are rejected. `$defs/MicropynqManifest` and related
  schema definitions are renamed to `Nanopynq*`. Registry rows are migrated
  in place (`platforms.runtime`).
- Client-consumed API response models switched from `extra="forbid"` to
  `extra="ignore"` (tolerant reader, ADR-014). Additive response-field
  changes no longer break released CLI/SDK clients **from this version on**.
  OpenAPI response schemas drop `additionalProperties: false` accordingly
  (regenerated); request validation and local file-format schemas
  (design-index / platform-manifest / board-db) remain strict and unchanged.
- Client resolution (`docs/specs/client-behavior.md` §6) — pull 時のプラットフォーム解決に
  family fallback（exact miss 時に board-db の `device_family` で
  `generic-{device_family}/{runtime}` を再解決）を導入し、旧 §6 の
  「pull 時 generic フォールバック MUST NOT」規範を撤回。
  wire 契約（OpenAPI / JSON Schema）は無変更で、従来エラー（exit 5）だったケースが
  成功に変わる方向のみの変化。由来は `fallback_from`（加算的 optional）で観測可能。
  根拠: `docs/specs/client-behavior.md` §6。

### Added
- `PlatformEntry.attestation` (`{transparency_log_url: string} | null`) on
  `VersionDetailResponse.platforms[]` — attestation **presence** signal for the
  trust badges UI (UI-TRUST-001). Additive only; `null` for platforms whose
  manifest declares no attestation (existing rows stay `null`, no backfill).
  The registry does not verify the attestation; clients verify locally via
  `fabricgate pull --verify-attestation`. Note: the version-detail endpoint is
  currently exposed with `response_model=None`, so the OpenAPI snapshot /
  generated client are unchanged by this addition (documented in
  `docs/specs/registry-api.md`).
  **既知の互換性注意（デプロイ順序）**: 本フィールドを返す registry に対し、
  本変更より前のモデルを持つ v0.x 以前の CLI/SDK は `VersionDetailResponse` が
  `extra="forbid"` のため version detail のパース（`client.get_version()`）に
  失敗する。**クライアント更新を registry 更新より先行させること。**
  リポジトリ内クライアントは puller strip（`_version_detail_to_index`）で対応済み。
  恒久策はクライアント消費レスポンスモデルの extra ポリシー forbid → ignore として
  ADR-014 で決定済み（上記 Changed 参照）。本注記は ADR-014 より前の
  v0.x クライアント世代にのみ適用される。
- Admin moderation endpoints (operator yank / namespace suspend) —
  `POST/DELETE /api/v1/admin/namespaces/{namespace}/designs/{design}/versions/{version}/yank`,
  `POST/DELETE /api/v1/admin/namespaces/{namespace}/suspend` (`platform:admin`, idempotent)
- `yanked_by` field (`"owner" | "operator" | null`) on `YankResponse` / `VersionDetailResponse`
- `NamespaceSuspendResponse` schema — `{namespace, status, suspended}`
- New error codes: `NAMESPACE_SUSPENDED` (403 on any access to a suspended namespace),
  `OPERATOR_YANKED` (403 when the owner tries to modify an operator-yanked version)
- Wire-format JSON Schemas (draft 2020-12) under `docs/contracts/schemas/`:
  `design-index.schema.json`, `platform-manifest.schema.json`, `board-db.schema.json`.
  Generated from the Pydantic models via `scripts/extract_schemas.py`;
  drift-gated in CI. Enables new-language SDK codegen against the file formats.

## [0.4.0] - 2026-06-11

### Changed
- `GET /api/v1/health` — response schema updated from `{status: string}` to
  `HealthResponse` with `status`, `database`, and `storage` fields.
  Returns HTTP 503 when any component is degraded.

### Added
- `ComponentHealth` schema — `{status: "ok"|"error"}`
- `HealthResponse` schema — `{status: "ok"|"degraded", database: ComponentHealth, storage: ComponentHealth}`

## [0.3.0] - 2026-03-25

### Added
- `DesignSummary.version_count` — number of published versions per design
- `DesignSummary.download_count` — download counter per design (stub: always 0)
- `RegistryStatsResponse.total_versions` — total published version count

## [0.2.0] - 2026-03-25

### Added
- Full OpenAPI 3.1.0 snapshot with all 21 endpoints (auth, designs, namespaces, health)
- `openapi.json` derived file for Swagger UI and frontend codegen
- Frontend TypeScript client generated via `openapi-typescript-codegen`
- CI contract-drift detection job
- Taskfile tasks: `generate-openapi`, `generate-frontend-client`, `generate-api`

## [0.1.0] - 2026-03-22

### Added
- Initial health check endpoint (`GET /api/v1/health`)
