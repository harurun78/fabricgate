# API Contract Changelog

Sections are named after the `fabricgate` package release tag (`vX.Y.Z`) that
first shipped the change. Changes not yet in a tagged release are listed under
`[Unreleased]`.

## [Unreleased]

### Added

- `fabricgate pull` shows a download bar per artifact (root, dependencies, shell) on stderr while stderr is a terminal; cached artifacts show as complete. Nothing changes when stderr is not a terminal, and stdout (including `--json`) is unchanged. The SDK's `pull()` and `fabricgate.client.puller.pull_design()` accept `on_progress(label, bytes_received, total_bytes)`, and `RegistryClient.download_artifact()` accepts `on_progress(bytes_received, total_bytes)`, which `pull_design()` passes only when a callback is given, so existing `RegistryClientProtocol` implementations keep working at runtime (type-checked implementations need the new keyword argument to match the protocol). `total_bytes` is the `Content-Length`, or `None` without one. No API or schema change.
- `github_login` (string or null) on `UserProfileResponse` (`GET /api/v1/users/me`, `POST /api/v1/oauth/signup`), `NamespaceMemberResponse` (the namespace members list, add and role change) and `AdminUserEntry` (the admin user list): the GitHub login of the linked account as of the user's last sign-in, or null for other identity providers and for users who have not signed in since the registry started recording it. A username can differ from the GitHub login (a new user chooses one when the GitHub login is reserved or taken), so this shows whose account it is. Optional and additive; existing clients ignore it.
- `POST /api/v1/oauth/signup` (request `SignupRequest`, response `UserProfileResponse`, `201`): a new user whose identity provider name (for example the GitHub login) is reserved, or already used by another user or namespace, chooses another username in the web UI. The registry's web frontend calls it with the pending sign-in it set at `GET /api/v1/oauth/callback`; no CLI/SDK code calls it. The username follows the namespace name rules (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`, 1-39 characters). Errors: `422 SCHEMA_VALIDATION_FAILED` (`username` empty or over 64 characters), `400 INVALID_PARAMETER` (any other username outside the rules), `401 UNAUTHORIZED` (the pending sign-in expired), `403 FORBIDDEN` (CSRF), `409 RESERVED_NAMESPACE` / `409 USERNAME_TAKEN`.

### Changed

- `fabricgate verify` (and the SDK's `verify()`) also checks the dependencies under `deps/{namespace}/{design}/{version}/` and the shell under `shell/{namespace}/{design}/{version}/`, the same way as the root: the artifacts against each manifest and, unless `--offline`, each manifest against the registry. Each one is checked against the version its path names, and a manifest whose `design_ref` differs from its path fails with exit 3. The shell must also carry the artifact whose sha256 the root manifest's `shell_dependency` pins. Before, only the root directory was checked, so a rewritten dependency or shell went unnoticed. Required dependencies and the shell that the root manifest declares but that were not pulled are listed, not failed. `VerificationResult` gains `dependencies`, `shells` and `missing`. No API or schema change.
- **BREAKING (CLI/SDK)**: `fabricgate verify` (and the SDK's `verify()`) first checks the manifest against the registry: the SHA-256 of the manifest file must equal the `digest` of a platform of the version in `GET .../versions/{version}`. Before, only the artifacts were checked against the local manifest, so rewriting both the manifest and the artifacts after a pull went unnoticed. `--ref` (SDK `ref`) pins the version, which otherwise comes from the manifest's `design_ref`; `--platform` (SDK `platform`) pins the platform, which otherwise may be any platform of the version. A manifest that matches no platform fails with exit 3, a missing version or platform with exit 1, and an unreachable registry with exit 4; there is no automatic fallback. `--offline` (SDK `offline=True`) keeps the old artifact-only check, so offline use and scripts that must not reach the network need it. A version published before the registry checked the index `digest` may carry a stale one; a genuine pull of it then fails with exit 3 until the registry's digest is corrected, so the message names both causes and suggests `--offline`. The SDK's `registry` argument (default: the public registry) selects the registry to check against. A yanked version prints a warning. `VerificationResult` gains `manifest_verified`, `checked_ref`, `checked_platform`, `yanked` and `yanked_reason`. No API or schema change.
- `GET /api/v1/oauth/callback`: when a new user's identity provider name is reserved or already used, the registry redirects to the frontend's username form (`/auth/username`) instead of `/login?error=user_resolve_failed`. No session is set until the user is created.
- `POST /api/v1/oauth/token`: on the same collision the `409` code is unchanged (`USERNAME_TAKEN` / `RESERVED_NAMESPACE`), and the message now tells the user to sign in on the web to choose a username and then log in again. `fabricgate login` prints the message as is.
- Username and namespace collisions are checked ignoring case: a new user `Alice` is refused when `alice` exists as a username or namespace, and a namespace `alice` cannot be created by anyone but user `Alice`.
- **BREAKING (schema)**: Design Index `repository` and `docs` must be `http://` or `https://` URLs without whitespace (`^https?://\S+$`). They are shown as links, so `javascript:`, `file:`, `data:` and other schemes are rejected. `fabricgate push` refuses such an index, and so does a registry that validates with this model. `fabricgate pull` ignores both fields, so versions published earlier with other values still pull. `design-index.schema.json` is regenerated.
- `fabricgate quota` prints sizes the way `fabricgate diff` does: whole numbers without a decimal (`1 GB`, `500 MB`) and one decimal otherwise (`4.4 GB`). It printed `1.0 GB` and `500.0 MB` before. Only the text output changes; `--json` is unchanged. No API or schema change.
- `fabricgate pull` (and the SDK's `pull(cache_dir=...)`) reuses artifacts from the local cache. Root, dependency and shell artifacts are looked up by the sha256 their manifest pins, under `<cache-dir>/blobs/sha256/`. A cached file is hashed again before use and downloaded again when it does not match. Manifests are still fetched every time, and `--verify-attestation` still checks every signature. `PullResult.cached` is now `true` when all root artifacts came from the cache (it was always `false`), and the text output says `(from cache)`. `--no-cache` neither reads nor writes the cache. The cache has no size limit; delete `blobs/` to free the space. No API or schema change.
- `fabricgate yank` / `deprecate` / `deprecate --undo` (and the SDK's `yank()` / `deprecate()` / `undeprecate()`) with several versions still stop at the first failure, and the error now ends with the versions changed before it, for example `(1.0.0, 1.1.0 were yanked before this error)`. Before, only the failure was shown although the earlier versions had been changed. The exit code is unchanged. No API or schema change.
- `fabricgate search` takes `--device <device_family>`, the name the CLI specification uses (§3.3). `--device-family`, the name up to 0.4.4, still works but no longer shows up in `--help`. The SDK's `search(device_family=...)` and the API's `device_family` query are unchanged.
- `attestation.bundle` (platform manifest) is defined as a cosign bundle that signs that platform's `manifest.yaml` (`cosign sign-blob manifest.yaml --bundle <bundle>`). The manifest pins every artifact by sha256, so the one signature covers the platform. `fabricgate pull --verify-attestation` downloads it from `artifacts/{bundle}`. No schema change.
- Publish (`POST .../versions/{version}`) accepts an optional part `platform:{board_id}/{runtime}:attestation:{bundle}`, and add platform accepts `attestation:{bundle}`: the bundle sent inline (it cannot be pinned by sha256 in the manifest it signs, so it does not use the direct upload). The registry stores it like an inline artifact and serves it from `artifacts/{bundle}`. Without the part, publish behaves as before. `fabricgate push` sends the part when the bundle file exists next to the manifest and warns when it does not.
- **BREAKING (Registry API)**: `DELETE /api/v1/admin/users/{username}` accepts an optional `force` query (boolean, default `false`). Without it, deleting a user who is the sole owner of a namespace is refused with `409 SOLE_OWNER`, and the message names those namespaces; add another owner first. With `force=true` the user is deleted and those namespaces are left without an owner, as every delete did before. No CLI/SDK code calls this endpoint, but admin scripts that delete sole owners now get `409` instead of `204`; they need to add another owner first or pass `force=true`.
- `fabricgate pull --verify-attestation` now verifies each manifest (root, dependencies, shell) against a required signer: `--attestation-key`, or `--certificate-identity` with `--certificate-oidc-issuer`. A manifest without `attestation`, or one whose `design_ref` / `runtime` differs from what was requested, fails verification. `--verify-attestation` cannot be combined with `--no-verify`.
- `fabricgate pull` extracts each dependency to `deps/{namespace}/{design}/{version}/` and the shell to `shell/{namespace}/{design}/{version}/` (was `deps/{namespace}-{design}-{version}/` and `shell/{namespace}-{design}-{version}/`). Hyphen-joined names collided because namespaces and designs may contain hyphens: `a-b/c:1.0.0` and `a/b-c:1.0.0` both went to `deps/a-b-c-1.0.0/`. Scripts that read the old paths need updating. No API or schema change.
- `fabricgate push` (and the SDK's `push()`) computes each index platform `digest` from the platform manifest it uploads and sends that value; the local index file is not changed. The placeholder that `fabricgate build` writes (`sha256:aaa…a`, or any 64 copies of one character) is no longer refused, and a hand-written digest that differs from the manifest prints a warning (`PushResult.sha_warning`) instead of being sent as is. `--board` promotion already recomputed the digest of the rewritten manifest. No API or schema change on the client side.
- **BREAKING (Registry API)**: publish (`POST .../versions/{version}`) rejects a Design Index whose platform `digest` is not the SHA-256 of the platform manifest uploaded with it (`400 DIGEST_MISMATCH`), as the API specification requires; before, the registry stored and returned the declared value. Clients up to 0.4.4 send the index file as is, so a project whose index digest is stale fails to publish until it is upgraded or the digest is corrected. Adding a platform to an existing version (`POST .../versions/{version}/platforms/{board_id}/{runtime}`) already stored the digest computed from the uploaded manifest. The OpenAPI document is unchanged.
- The CLI and SDK use `httpx2` instead of `httpx` for HTTP. HTTPS certificates are now verified against the operating system's trust store instead of the `certifi` bundle (through `truststore` on Windows and macOS, and OpenSSL's system CA paths on Linux); `SSL_CERT_FILE` / `SSL_CERT_DIR`, when set, take precedence. Environments without system CA certificates (for example minimal container images) need them installed or `SSL_CERT_FILE` set. The `User-Agent` header is now `python-httpx2/<version>`. No API or schema change.
- `GET /api/v1/oauth/callback`: `code` is optional and an optional `error` query is accepted. When the identity provider redirects back with `error` (for example, the user cancelled on the consent screen) or without `code`, the registry skips the state check and the token exchange, clears the OAuth flow cookies and redirects to `/login?error=<reason>` on the frontend. `<reason>` is the received `error` if it is one of the RFC 6749 §4.1.2.1 error codes, otherwise `oauth_failed`. Before, such a request failed with `422`. Only the identity provider's redirect reaches this endpoint; no CLI/SDK code calls it.

### Removed

- **BREAKING (Python API)**: `fabricgate.client.lookup()` and `fabricgate.client.platform_dir()` are removed (also from `fabricgate.client.cache`). Nothing called them: `lookup()` matched `index.json` records, which do not decide cache hits (artifacts are looked up by sha256 under `blobs/`), and `platform_dir()` returned a cache path nothing writes to. Code that imported them must drop the import. No CLI, API or schema change.
- **BREAKING (Registry API)**: `POST /api/v1/admin/mirror/sync` is removed.
  The registry drops its periodic "sync" mirror mode (full replication from an
  upstream registry); the pull-through mirror mode stays. The endpoint was
  admin-only, no CLI/SDK call used it, and the sync mode it triggered could not
  replicate anything from a FabricGate upstream. The registry now answers `404`.
  `GET /api/v1/admin/mirror/sync-log` and `MirrorSyncLogResponse` are unchanged;
  the log keeps recording pull-through results.

## [0.4.4] - 2026-10-23

No contract changes.

## [0.4.3] - 2026-10-23

No contract changes.

## [0.4.2] - 2026-10-23

No contract changes.

## [0.4.1] - 2026-10-22

### Docs

- `platform-manifest-schema.md`: `pynq_version` is a version range, not a minimum. Publishers should write an upper bound (e.g. `">=3.0.1,<4"`) because PYNQ v4 is not compatible with 3.x overlays. The field stays informational; no schema or model change.

### Fixed
- `fabricgate login` / `sdk.login`: a `429` from `POST /api/v1/oauth/token` while polling the device flow no longer aborts the login; the client waits for `Retry-After` (seconds or HTTP-date, never less than the poll interval; the interval when the header is missing or invalid) and fails with a clear rate-limit error (exit 3) only when that wait would outlast the device code (`expires_in`).
- Version patterns now reject non-ASCII digits. `SemVer`, `DesignRef`, the Platform Manifest `dependencies[].version` constraint and `shell_dependency.version` used `\d`, which also matches other Unicode decimal digits (e.g. `1٠.0.0` with an Arabic-Indic zero, or full-width `１`); they now use `[0-9]` (OpenAPI and JSON Schema patterns updated). In `dependencies[].version`, the first character after the version (the start of the separator) is narrowed from `\s` (any whitespace, including newline and tab) to a space, matching the "space-separated" wording in `docs/specs/platform-manifest-schema.md`; the rest of the constraint (`.+`) is unchanged, so e.g. `1.0.0 \t<2.0.0` still passes, and tightening it is out of scope here. The relative `<N>d` form of `fabricgate token create --expires` / the SDK likewise accepts ASCII digits only. Not a breaking change: SemVer 2.0.0 defines version numbers with the digits 0-9 only, and the registry's resolver already fails on any constraint with a trailing part, so no value that worked before is now refused.

### Changed
- Platform Manifest: the `NanopynqArtifacts` description now states that the
  `nanopynq` artifact set is a fabricgate / nanopynq convention, not an external
  standard (`docs/specs/platform-manifest-schema.md` §5). Description only; the
  schema structure is unchanged.

### Registry behavior changes (no wire change)
- Namespace write permission is now decided by namespace membership only
  (`owner` / `admin` / `write` rows in `namespace_members`). The shortcut that
  granted write access to the namespace whose name equals the caller's
  username is removed. The wire contract (OpenAPI / JSON Schema) is unchanged;
  a user who relied on the shortcut and has no membership row now gets `403`
  on writes to that namespace. Self-hosted operators should check, before and
  after upgrading the registry, for namespaces that have no `owner` member and
  add the intended owner.

## [0.4.0] - 2026-10-06

### Changed
- **BREAKING (Registry API)**: `NamespaceMemberResponse` drops `email`.
  The member list, add-member and role-change responses
  exposed other members' email addresses to namespace admins. The field was
  optional, so released CLI/SDK clients still parse the responses; only code
  that read `email` loses it.

## [0.3.0] - 2026-10-06

### Changed
- **BREAKING (Registry API)**: request-validation errors (`422`, FastAPI's
  `RequestValidationError`) now use the standard envelope
  `{"error": {"code": "SCHEMA_VALIDATION_FAILED", "message": "query.page: ..."}}`
  instead of `{"detail": [...]}`. The message joins up to ten
  `location: message` pairs and never echoes the input value.
  - OpenAPI: every 422 that referenced `HTTPValidationError` now references
    `ErrorResponse`; the `HTTPValidationError` and `ValidationError` schemas are
    removed (regenerated).
  - Released SDKs could not parse the old body and raised `NetworkError`
    (`FailureKind.INFRA`); they now raise `RegistryError` with
    `FailureKind.INVALID`, as for other 422s.

### Added
- API keys (spec §3.9): `POST` / `GET` / `PATCH` / `DELETE
  /api/v1/users/me/api-keys` and `fabricgate.models.api.requests.ApiKeyCreateRequest`
  / `ApiKeyUpdateRequest`. `ApiKeyInfo` gains `revoked_at` (optional, additive).
  `ErrorCode` gains `INVALID_SCOPE`, `SCOPE_EXCEEDS_CALLER`, `API_KEY_NOT_ALLOWED`,
  `API_KEY_NOT_FOUND` and `API_KEY_LIMIT_EXCEEDED`. All four endpoints need
  interactive auth; an `fgk_` key is accepted as a Bearer token for namespace
  writes within its `ns:{namespace}:write` scopes.

## [0.2.0] - 2026-10-05

### Added
- `fabricgate.models.api.responses.UserProfileResponse` (`username`,
  `namespace`, `email`, `created_at`) and the `GET /users/me` success-response
  schema that references it. Same fields as before, so
  additive for clients.
  - Wire note: `created_at` is now serialized by pydantic like every other
    response model, so a UTC timestamp reads `...Z` instead of `...+00:00`.
    Both are RFC 3339 and parse to the same instant.
- OpenAPI success-response schemas for 14 registry operations that were
  previously documented as `schema: {}`. Documentation only:
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

### Removed
- **BREAKING (Registry API)**: `POST /api/v1/users/me/username` and its models
  `fabricgate.models.api.requests.UsernameSetupRequest` /
  `fabricgate.models.api.responses.UsernameSetupResponse` are removed.
  Usernames are set automatically at the first OAuth login,
  and no client calls this endpoint (the CLI/SDK never did). The endpoint also
  accepted an existing namespace's name as a new username, which granted write
  access to that namespace. The registry now answers `404`.
- **BREAKING (models)**: `ErrorCode.STATS_PRIVATE` is removed.
  The registry has no private namespaces and never returned this code; the
  download-stats routes are public, and a suspended namespace answers
  `403 NAMESPACE_SUSPENDED` as before. The wire format is unchanged
  (`ErrorDetail.code` is a plain string); only code that references the enum
  member breaks.
  - OpenAPI: the `GET /api/v1/namespaces/{namespace}/stats` description no
    longer says "public for non-private namespaces" (regenerated; no schema
    change).

## [0.1.3] - 2026-09-24

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

## [0.1.2] - 2026-09-24

### Added
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

## [0.1.1] - 2026-09-15

No contract changes.

## [0.1.0] - 2026-09-15

Initial public release. Includes the contract changes made before the
repository was published.

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

## Contract schema history before the public repository

The entries below are versions of the API contract schema, recorded before
this repository existed. Their numbers are not `fabricgate` package releases:
contract schema 0.4.0 (2026-06-11) is unrelated to package v0.4.0
(2026-10-06).

### [0.4.0] - 2026-06-11

#### Changed
- `GET /api/v1/health` — response schema updated from `{status: string}` to
  `HealthResponse` with `status`, `database`, and `storage` fields.
  Returns HTTP 503 when any component is degraded.

#### Added
- `ComponentHealth` schema — `{status: "ok"|"error"}`
- `HealthResponse` schema — `{status: "ok"|"degraded", database: ComponentHealth, storage: ComponentHealth}`

### [0.3.0] - 2026-03-25

#### Added
- `DesignSummary.version_count` — number of published versions per design
- `DesignSummary.download_count` — download counter per design (stub: always 0)
- `RegistryStatsResponse.total_versions` — total published version count

### [0.2.0] - 2026-03-25

#### Added
- Full OpenAPI 3.1.0 snapshot with all 21 endpoints (auth, designs, namespaces, health)
- `openapi.json` derived file for Swagger UI and frontend codegen
- Frontend TypeScript client generated via `openapi-typescript-codegen`
- CI contract-drift detection job
- Taskfile tasks: `generate-openapi`, `generate-frontend-client`, `generate-api`

### [0.1.0] - 2026-03-22

#### Added
- Initial health check endpoint (`GET /api/v1/health`)
