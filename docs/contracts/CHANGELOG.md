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
- `fabricgate.models.api.responses.UserProfileResponse` (`username`,
  `namespace`, `email`, `created_at`) and the `GET /users/me` success-response
  schema that references it (registry #979). Same fields as before, so
  additive for clients.
  - Wire note: `created_at` is now serialized by pydantic like every other
    response model, so a UTC timestamp reads `...Z` instead of `...+00:00`.
    Both are RFC 3339 and parse to the same instant.
- OpenAPI success-response schemas for 14 registry operations that were
  previously documented as `schema: {}` (registry #853). Documentation only:
  the wire format, status codes of JSON routes and error responses are
  unchanged. 11 component schemas are added (`DesignDetailResponse`,
  `VersionDetailResponse`, `VersionSummary`, `ApiPlatformEntry`,
  `ArtifactInfo`, `AttestationInfo`, `ShellDependency`, `SpeedGrade`,
  `PublishResponse`, `PlatformAddResponse`, `UsernameSetupResponse`).
  - JSON bodies now reference their models: design detail, version detail,
    publish (`201`), yank, platform add (`201`), `POST /users/me/username`,
    `GET /users/me/designs` (`DesignSummary[]`), namespace create / get /
    verify (`NamespaceResponse`), namespace quota get / patch (`QuotaResponse`).
  - `GET .../platforms/{board_id}/{runtime}` (platform manifest) is documented
    as `200 application/x-yaml` (string) instead of `application/json`.
  - `GET .../artifacts/{filename}` is documented as `307` (redirect to the
    download URL) instead of `200`; the server already answered `307`.
  - `GET /users/me` stays undocumented (no public model yet).
- `ArtifactInfo.source` (`"registry" | "external"`, optional) on
  `VersionDetailResponse.platforms[].artifacts[]` / design detail. `"external"`
  marks an artifact published by URL (`fabricgate push --artifact-url`): the
  registry fetched it once at publish time to verify the manifest `sha256` and
  the download endpoint answers `307` to that URL. Additive only; older servers
  omit it and tolerant readers yield `null`. `pull` needs no change.
- Publish request (multipart): new text part
  `platform:{board_id}/{runtime}:artifact-url:{filename}` (body = the `https`
  URL) on `POST .../versions/{version}`, and `artifact-url:{filename}` on the
  incremental add route `POST .../versions/{version}/platforms/{board_id}/{runtime}`.
  For that filename the client sends no `artifact:{filename}` part and requests
  no upload ticket; both for one file → `400 INVALID_REQUEST`. Server-side
  validation: `https` only, no userinfo, ≤ 2048 chars, operator host allowlist,
  per-hop redirect checks, fetch size cap (`413 PAYLOAD_TOO_LARGE`), digest
  compared to the manifest (`400 DIGEST_MISMATCH`). External bytes do not count
  toward the namespace storage quota. `openapi.*` is regenerated from the
  registry app and lands in a follow-up once it pins this model revision.
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

### Removed
- **BREAKING (Registry API)**: `POST /api/v1/users/me/username` and its models
  `fabricgate.models.api.requests.UsernameSetupRequest` /
  `fabricgate.models.api.responses.UsernameSetupResponse` are removed
  (registry #994). Usernames are set automatically at the first OAuth login,
  and no client calls this endpoint (the CLI/SDK never did). The endpoint also
  accepted an existing namespace's name as a new username, which granted write
  access to that namespace. The registry now answers `404`.
- **BREAKING (models)**: `ErrorCode.STATS_PRIVATE` is removed (registry #1020).
  The registry has no private namespaces and never returned this code; the
  download-stats routes are public, and a suspended namespace answers
  `403 NAMESPACE_SUSPENDED` as before. The wire format is unchanged
  (`ErrorDetail.code` is a plain string); only code that references the enum
  member breaks.
  - OpenAPI: the `GET /api/v1/namespaces/{namespace}/stats` description no
    longer says "public for non-private namespaces" (regenerated; no schema
    change).

### Fixed
- `POST /api/v1/oauth/token` success body: the client now reads the standard
  OAuth token response (RFC 6749 §5.1: `access_token`, `expires_in`, `scope`,
  `refresh_token`), which is what the registry returns. `expires_at` is
  computed client-side as receipt time + `expires_in`, `scopes` is
  `scope.split()`. The flat `{token, expires_at, scopes}` shape the client
  previously required is still accepted. `refresh_token` is kept in the stored
  credentials (new optional field; no refresh grant is sent yet).
- Error bodies in the raw OAuth form (RFC 6749 §5.2,
  `{"error": "authorization_pending", "error_description": "…"}`) are mapped to
  the error envelope with `code = error.upper()` (e.g. `AUTHORIZATION_PENDING`,
  `SLOW_DOWN`) instead of surfacing as a network error. Applies to every
  endpoint; enveloped errors are unchanged.

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
