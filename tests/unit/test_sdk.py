"""Unit tests for public SDK APIs."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

import fabricgate.client.puller as _puller_mod
import fabricgate.sdk.auth as _sdk_auth_mod
import fabricgate.sdk.designs as _sdk_designs_mod
import fabricgate.sdk.webhooks as _sdk_webhooks_mod
from fabricgate.client.puller import AttestationError, AttestationUnavailableError, IntegrityError
from fabricgate.models.api.responses import (
    ArtifactUploadResponse,
    ArtifactUploadTicket,
    DesignStatsResponse,
    LicenseCheckResponse,
    LoginResponse,
    NamespaceStatsResponse,
    PublishResponse,
    QuotaResponse,
    SearchResponse,
    VersionDetailResponse,
    VersionDiffField,
    VersionDiffPlatform,
    VersionDiffResponse,
    VersionDiffSummary,
    VersionStatsResponse,
)
from fabricgate.models.api.responses import (
    LicenseCheckResult as ApiLicenseCheckResult,
)
from fabricgate.models.cli import DesignStatsInfo, LicenseCheckInfo, NamespaceStatsInfo
from fabricgate.models.platform_manifest import ToolRequirement
from fabricgate.sdk import api as sdk_api
from fabricgate.sdk._helpers import ExitKind

# ``designs`` is a package whose submodules are shadowed by same-named re-exported
# functions on the package; resolve the real ``push`` submodule (the monkeypatch
# target for load_design_index / collect_artifacts) via importlib.
_sdk_designs_push_mod = importlib.import_module("fabricgate.sdk.designs.push")


@pytest.fixture(autouse=True)
def _no_stored_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep SDK tests hermetic: never read the developer's real credential store.

    ``pull`` (and other SDK functions) auto-resolve stored credentials via
    ``auth.load_credentials``; without this stub, tests would hit the real
    keyring / ``~/.fabricgate/credentials.json``. Tests that exercise credential
    resolution override this stub with their own ``monkeypatch.setattr`` (test
    bodies run after autouse fixtures, so their patch wins).
    """
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)


def _patch_all_rc(monkeypatch: pytest.MonkeyPatch, fake_client: type) -> None:
    """Patch RegistryClient in all SDK domain modules.

    ``designs`` is a package whose submodules each import RegistryClient, so we
    patch every submodule that references it (the package ``__init__`` only
    re-exports functions).
    """
    import pkgutil

    monkeypatch.setattr(_sdk_auth_mod, "RegistryClient", fake_client)
    monkeypatch.setattr(_sdk_webhooks_mod, "RegistryClient", fake_client)
    for _modinfo in pkgutil.iter_modules(_sdk_designs_mod.__path__):
        _submod = importlib.import_module(f"{_sdk_designs_mod.__name__}.{_modinfo.name}")
        if hasattr(_submod, "RegistryClient"):
            monkeypatch.setattr(_submod, "RegistryClient", fake_client)


class _FakeRegistryClient:
    def __init__(self, *_args, **_kwargs) -> None:
        bitstream = b"bitstream-data"
        hwh = b"<hwh/>"
        self.manifest_bytes = "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: test-ns/blink:1.0.0",
                "artifacts:",
                "  bitstream:",
                "    file: design.bit",
                f"    sha256: {hashlib.sha256(bitstream).hexdigest()}",
                "  hwh:",
                "    file: design.hwh",
                f"    sha256: {hashlib.sha256(hwh).hexdigest()}",
            ]
        ).encode("utf-8")

    def __enter__(self) -> _FakeRegistryClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def search_designs(self, **_kwargs) -> SearchResponse:
        return SearchResponse.model_validate(
            {
                "designs": [
                    {
                        "name": "test-ns/blink",
                        "latest_version": "1.0.0",
                        "summary": "Blink demo",
                        "platforms": ["xc7z020/pynq"],
                        "tags": ["demo"],
                        "updated_at": datetime(2026, 3, 17, tzinfo=UTC),
                    }
                ],
                "total": 1,
                "page": 1,
                "per_page": 20,
            }
        )

    def get_version(self, namespace: str, design: str, version: str) -> VersionDetailResponse:
        assert (namespace, design, version) == ("test-ns", "blink", "1.0.0")
        return VersionDetailResponse.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": "test-ns/blink",
                "version": "1.0.0",
                "summary": "Blink demo",
                "license": "MIT",
                "author": "FabricGate",
                "repository": "https://example.com/blink",
                "tags": ["demo"],
                "platforms": [
                    {
                        "platform": "xc7z020/pynq",
                        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
                "published_at": datetime(2026, 3, 17, tzinfo=UTC),
            }
        )

    def get_platform_manifest_bytes(self, *_args) -> bytes:
        return self.manifest_bytes

    def download_artifact(self, *_args) -> bytes:
        filename = _args[-1]
        if filename == "design.bit":
            return b"bitstream-data"
        return b"<hwh/>"

    def get_dependencies(self, *_args, **_kwargs):
        from fabricgate.models.api.responses import DependenciesResponse

        return DependenciesResponse(root="test-ns/blink:1.0.0", platform="xc7z020/pynq", dependencies=[])

    def get_shell(self, *_args, **_kwargs):
        from fabricgate.client.registry_client import RegistryError
        from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

        raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="No shell")))

    def create_api_key(self, name, scopes, expires_at=None):
        from fabricgate.models.api.responses import ApiKeyCreateResponse

        return ApiKeyCreateResponse(
            id=42,
            name=name,
            key="fgk_abc123secrettoken",
            scopes=scopes,
            expires_at=expires_at,
            created_at=datetime(2026, 3, 29, tzinfo=UTC),
        )

    def list_api_keys(self):
        from fabricgate.models.api.responses import ApiKeyInfo, ApiKeyListResponse

        return ApiKeyListResponse(
            api_keys=[
                ApiKeyInfo(
                    id=1,
                    name="key-alpha",
                    scopes=["public:read"],
                    expires_at=datetime(2027, 6, 1, tzinfo=UTC),
                    last_used_at=datetime(2026, 3, 28, tzinfo=UTC),
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ]
        )

    def delete_api_key(self, key_id):
        if key_id == 999:
            from fabricgate.client.registry_client import RegistryError
            from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="API key not found")))


def test_search_returns_sdk_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _FakeRegistryClient)
    results = sdk_api.search("blink")
    assert len(results) == 1
    assert results[0].name == "test-ns/blink"
    assert results[0].version == "1.0.0"


def test_info_returns_version_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _FakeRegistryClient)
    result = sdk_api.info("test-ns/blink:1.0.0")
    assert result.name == "test-ns/blink"
    assert result.version == "1.0.0"
    assert result.platforms[0].platform == "xc7z020/pynq"


def test_verify_checks_local_artifacts(tmp_path: Path) -> None:
    bitstream = b"bitstream-data"
    hwh = b"<hwh/>"
    (tmp_path / "design.bit").write_bytes(bitstream)
    (tmp_path / "design.hwh").write_bytes(hwh)
    (tmp_path / "manifest.yaml").write_text(
        "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: test-ns/blink:1.0.0",
                "artifacts:",
                "  bitstream:",
                "    file: design.bit",
                f"    sha256: {hashlib.sha256(bitstream).hexdigest()}",
                "  hwh:",
                "    file: design.hwh",
                f"    sha256: {hashlib.sha256(hwh).hexdigest()}",
            ]
        ),
        encoding="utf-8",
    )

    result = sdk_api.verify(tmp_path)
    assert all(item.verified for item in result.artifacts)


def test_version_detail_to_index_strips_api_enrichment_fields() -> None:
    """Additive API-response enrichments must not break DesignIndex validation on pull.

    The registry enriches platform entries with API-only fields (``artifacts``,
    ``attestation``); the strict DesignIndex schema rejects extras, so the
    puller must strip them (UI-TRUST-001 regression).
    """
    from fabricgate.client.puller import _version_detail_to_index

    idx = _version_detail_to_index(
        {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Blink demo",
            "license": "MIT",
            "platforms": [
                {
                    "platform": "xc7z020/pynq",
                    "digest": "sha256:" + "a" * 64,
                    "artifacts": [{"filename": "design.bit", "sha256": "b" * 64, "size": 1}],
                    "attestation": {"transparency_log_url": "https://rekor.example/log/1"},
                }
            ],
        }
    )
    assert idx.platforms[0].platform == "xc7z020/pynq"


def test_pull_downloads_manifest_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_all_rc(monkeypatch, _FakeRegistryClient)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert result.platform == "xc7z020/pynq"
    assert result.fallback_from is None
    assert (tmp_path / "manifest.yaml").exists()
    assert (tmp_path / "design.bit").exists()
    assert (tmp_path / "design.hwh").exists()


class _FakeGenericOnlyRegistryClient(_FakeRegistryClient):
    """Fake whose index only publishes the generic-xc7z020/pynq platform."""

    def get_version(self, namespace: str, design: str, version: str) -> VersionDetailResponse:
        assert (namespace, design, version) == ("test-ns", "blink", "1.0.0")
        return VersionDetailResponse.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": "test-ns/blink",
                "version": "1.0.0",
                "summary": "Blink demo",
                "platforms": [
                    {
                        "platform": "generic-xc7z020/pynq",
                        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
                "published_at": datetime(2026, 3, 17, tzinfo=UTC),
            }
        )


def test_pull_family_fallback_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pull with a real board id succeeds via generic family fallback and carries provenance."""
    _patch_all_rc(monkeypatch, _FakeGenericOnlyRegistryClient)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="pynq-z2/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert result.platform == "generic-xc7z020/pynq"
    assert result.fallback_from == "pynq-z2/pynq"
    assert (tmp_path / "design.bit").exists()


def test_search_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """search: a transport NetworkError maps to SDKError INFRA (exit 4)."""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def search_designs(self, **_kwargs) -> SearchResponse:
            raise NetworkError("Network error: connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.search("blink", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_info_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """info: a transport NetworkError maps to SDKError INFRA (exit 4)."""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def get_version(self, *_args, **_kwargs) -> VersionDetailResponse:
            raise NetworkError("Network error: connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.info("test-ns/blink:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_pull_network_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """pull: a transport error mid-download maps to SDKError INFRA (exit 4), not a traceback."""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def download_artifact(self, *_args) -> bytes:
            raise NetworkError("Network error: connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            output=tmp_path,
            cache_dir=tmp_path / "cache",
        )
    assert exc_info.value.code == ExitKind.INFRA


# ============================================================================
# login
# ============================================================================


class _FakeLoginRegistryClient:
    """Fake client for Device Authorization Grant tests."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._poll_count = 0

    def __enter__(self) -> _FakeLoginRegistryClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def device_authorization(self) -> dict[str, Any]:
        return {
            "device_code": "DEVCODE",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.com/device",
            "interval": 0,  # no delay in tests
        }

    def token_exchange(self, **_kwargs: str) -> LoginResponse:
        self._poll_count += 1
        if self._poll_count < 2:
            from fabricgate.client.registry_client import RegistryError
            from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="AUTHORIZATION_PENDING", message="")),
            )
        return LoginResponse(
            token="tok-test-123",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            scopes=["openid", "profile"],
        )


def test_login_device_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_all_rc(monkeypatch, _FakeLoginRegistryClient)
    # Override save_credentials to write to temp path instead of real keyring
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: None)

    codes: list[tuple[str, str]] = []

    def on_code(uri: str, code: str) -> None:
        codes.append((uri, code))

    result = sdk_api.login(
        registry="https://example.com/api/v1",
        poll_interval=0,
        on_user_code=on_code,
    )
    assert result.registry == "https://example.com/api/v1"
    assert len(codes) == 1
    assert codes[0] == ("https://example.com/device", "ABCD-EFGH")


def test_login_saves_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_all_rc(monkeypatch, _FakeLoginRegistryClient)

    saved: list[Any] = []
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: saved.append(cred))

    sdk_api.login(registry="https://example.com/api/v1", poll_interval=0)
    assert len(saved) == 1
    assert saved[0].token == "tok-test-123"
    assert saved[0].registry == "https://example.com/api/v1"


class _SlowDownThenSucceedClient(_FakeLoginRegistryClient):
    """SLOW_DOWN on first poll, then succeed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._exchange_count = 0

    def token_exchange(self, **_kwargs: str) -> LoginResponse:
        self._exchange_count += 1
        if self._exchange_count == 1:
            from fabricgate.client.registry_client import RegistryError
            from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

            raise RegistryError(
                400,
                ErrorResponse(error=ErrorDetail(code="SLOW_DOWN", message="")),
            )
        return LoginResponse(
            token="tok-slow-down",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            scopes=["openid"],
        )


class _AuthDeclinedClient(_FakeLoginRegistryClient):
    """Always raises non-retryable error from token_exchange."""

    def token_exchange(self, **_kwargs: str) -> LoginResponse:
        from fabricgate.client.registry_client import RegistryError
        from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

        raise RegistryError(
            400,
            ErrorResponse(error=ErrorDetail(code="ACCESS_DENIED", message="User denied")),
        )


def test_login_slow_down_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """SLOW_DOWN → intervalが増加しリトライが成功する。"""
    _patch_all_rc(monkeypatch, _SlowDownThenSucceedClient)
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: None)

    result = sdk_api.login(registry="https://example.com/api/v1", poll_interval=0)
    assert result.registry == "https://example.com/api/v1"


def test_login_auth_declined_raises_sdk_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """非AUTHORIZATION_PENDINGエラーでSDKErrorが発生する。"""
    _patch_all_rc(monkeypatch, _AuthDeclinedClient)
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: None)

    with pytest.raises(sdk_api.SDKError):
        sdk_api.login(registry="https://example.com/api/v1", poll_interval=0)


def test_login_parses_oauth_response_and_raw_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real client over HTTP: raw OAuth pending, enveloped pending, then an OAuth token body."""
    import httpx

    from fabricgate.client.registry_client import RegistryClient

    token_bodies = [
        (403, {"error": "authorization_pending"}),
        (400, {"error": {"code": "AUTHORIZATION_PENDING", "message": ""}}),
        (
            200,
            {
                "access_token": "at-oauth",
                "refresh_token": "rt-oauth",
                "expires_in": 86400,
                "scope": "openid offline_access",
                "token_type": "Bearer",
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/device_authorization"):
            return httpx.Response(
                200,
                json={"device_code": "D", "user_code": "U", "verification_uri": "https://x/d", "interval": 0},
            )
        status, body = token_bodies.pop(0)
        return httpx.Response(status, json=body)

    class _MockTransportClient(RegistryClient):
        def __init__(self, base_url: str, token: str | None = None) -> None:
            super().__init__(base_url=base_url, token=token)
            self._client = httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(_sdk_auth_mod, "RegistryClient", _MockTransportClient)
    monkeypatch.setattr(_sdk_auth_mod.time, "sleep", lambda _s: None)
    saved: list[Any] = []
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: saved.append(cred))

    before = datetime.now(tz=UTC)
    sdk_api.login(registry="https://example.com/api/v1", poll_interval=0)

    assert token_bodies == []
    (cred,) = saved
    assert cred.token == "at-oauth"
    assert cred.refresh_token == "rt-oauth"
    assert cred.scopes == ["openid", "offline_access"]
    assert (cred.expires_at - before).total_seconds() >= 86400


def test_login_keyring_storage_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """キーリングが利用可能な場合、storage labelに 'keychain' が含まれる。"""
    import sys
    from unittest.mock import MagicMock

    _patch_all_rc(monkeypatch, _FakeLoginRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "save_credentials", lambda cred, path=None: None)
    monkeypatch.setitem(sys.modules, "keyring", MagicMock())

    result = sdk_api.login(registry="https://example.com/api/v1", poll_interval=0)
    assert "keychain" in result.storage.lower()


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


class _FakePushRegistryClient:
    """Fake that returns a successful PublishResponse."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.upload_requests: list[list[dict[str, object]]] = []
        self.uploaded: list[tuple[str, str, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def create_artifact_uploads(
        self,
        namespace: str,
        design: str,
        artifacts: list[dict[str, object]],
    ) -> ArtifactUploadResponse:
        self.upload_requests.append(artifacts)
        return ArtifactUploadResponse(
            uploads=[
                ArtifactUploadTicket(
                    filename=str(item["filename"]),
                    sha256=str(item["sha256"]),
                    url=f"https://storage.example.com/{item['sha256']}",
                    headers={"x-amz-checksum-sha256": "b64"},
                    expires_in=900,
                )
                for item in artifacts
            ]
        )

    def upload_artifact(self, ticket: ArtifactUploadTicket, data: bytes) -> None:
        self.uploaded.append((ticket.filename, ticket.sha256, len(data)))

    def publish_version(
        self,
        namespace: str,
        design: str,
        version: str,
        files: dict[str, bytes],
    ) -> PublishResponse:
        return PublishResponse(
            name=f"{namespace}/{design}",
            version=version,
            platforms=["xc7z020/pynq"],
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def get_namespace_quota(self, namespace: str) -> QuotaResponse:
        return QuotaResponse.model_validate(
            {
                "namespace": namespace,
                "storage": {"used_bytes": 4_724_464_640, "limit_bytes": 5_368_709_120, "used_percent": 88.0},
                "versions_per_design": {"limit": 100},
                "designs": {"used": 12, "limit": 200},
                "file_size_limit_bytes": 524_288_000,
            }
        )


def _write_push_project(
    root: Path,
    *,
    placeholder_digest: bool = False,
    placeholder_artifact_sha: bool = False,
) -> None:
    """Create a minimal publishable project in *root*."""
    platform_dir = root / "xc7z020" / "pynq"
    platform_dir.mkdir(parents=True)

    bitstream = b"\x00\x01\x02\x03"
    hwh = b"<hwh/>"
    (platform_dir / "design.bit").write_bytes(bitstream)
    (platform_dir / "design.hwh").write_bytes(hwh)

    bit_sha = "a" * 64 if placeholder_artifact_sha else hashlib.sha256(bitstream).hexdigest()
    hwh_sha = hashlib.sha256(hwh).hexdigest()

    manifest_yaml = "\n".join(
        [
            "schema: fabricgate-platform/v1",
            "runtime: pynq",
            "board: pynq-z2",
            "design_ref: test-ns/blink:1.0.0",
            "artifacts:",
            "  bitstream:",
            "    file: design.bit",
            f"    sha256: {bit_sha}",
            "  hwh:",
            "    file: design.hwh",
            f"    sha256: {hwh_sha}",
        ]
    )
    (platform_dir / "manifest.yaml").write_text(manifest_yaml)

    digest = (
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        if placeholder_digest
        else f"sha256:{hashlib.sha256(manifest_yaml.encode()).hexdigest()}"
    )

    index_yaml = "\n".join(
        [
            "schema: fabricgate-index/v1",
            "name: test-ns/blink",
            "version: 1.0.0",
            "platforms:",
            "  - platform: xc7z020/pynq",
            f"    digest: {digest}",
        ]
    )
    (root / "fabricgate-index.yaml").write_text(index_yaml)


def test_push_publishes_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.push(
        tmp_path,
        registry="https://example.com/api/v1",
        token="tok-test",
    )
    assert result.name == "test-ns/blink"
    assert result.version == "1.0.0"
    assert "xc7z020/pynq" in result.platforms
    assert result.quota_warning == "上限に近づいています"


def test_push_uploads_artifacts_directly_and_publishes_metadata_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """artifact bytes go to storage, only metadata goes through the API."""
    captured: dict[str, object] = {}

    class _RecordingClient(_FakePushRegistryClient):
        def publish_version(self, namespace, design, version, files):
            captured["files"] = dict(files)
            captured["client"] = self
            return super().publish_version(namespace, design, version, files)

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _RecordingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    sdk_api.push(tmp_path, token="tok")

    files = captured["files"]
    assert not [key for key in files if ":artifact:" in key], "artifact bytes must not reach the API"
    assert "index" in files
    assert any(key.endswith(":manifest") for key in files)

    client = captured["client"]
    assert client.uploaded, "artifacts should have been PUT to storage"
    requested = client.upload_requests[0]
    assert all({"filename", "sha256", "size"} <= set(item) for item in requested)


def test_push_skips_upload_when_registry_already_stores_the_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """a ticket without a URL means the CAS object exists — no re-upload."""

    class _AllStoredClient(_FakePushRegistryClient):
        def create_artifact_uploads(self, namespace, design, artifacts):
            return ArtifactUploadResponse(
                uploads=[
                    ArtifactUploadTicket(filename=str(item["filename"]), sha256=str(item["sha256"]))
                    for item in artifacts
                ]
            )

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _AllStoredClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.push(tmp_path, token="tok")

    assert result.version == "1.0.0"


def test_push_fails_when_registry_omits_an_upload_ticket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """publishing without a ticket would 400 later — fail with a clear error."""

    class _EmptyTicketsClient(_FakePushRegistryClient):
        def create_artifact_uploads(self, namespace, design, artifacts):
            return ArtifactUploadResponse(uploads=[])

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _EmptyTicketsClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="no upload ticket"):
        sdk_api.push(tmp_path, token="tok")


def test_push_network_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """push: a transport error during publish maps to SDKError INFRA (exit 4)."""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakePushRegistryClient):
        def publish_version(self, *_args, **_kwargs) -> PublishResponse:
            raise NetworkError("Network error: connection refused")

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _NetworkErrorClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.push(tmp_path, registry="https://example.com/api/v1", token="tok-test")
    assert exc_info.value.code == ExitKind.INFRA


def test_push_quota_fetch_network_error_does_not_fail_publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The post-publish quota fetch is best-effort: a transport error there must
    not turn a successful publish into a failure — the result is returned with
    no quota warning."""
    from fabricgate.client.registry_client import NetworkError

    class _QuotaNetworkErrorClient(_FakePushRegistryClient):
        def get_namespace_quota(self, namespace: str) -> QuotaResponse:
            raise NetworkError("Network error: connection refused")

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _QuotaNetworkErrorClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.push(tmp_path, registry="https://example.com/api/v1", token="tok-test")
    assert result.name == "test-ns/blink"
    assert result.version == "1.0.0"
    assert result.quota_warning is None


def test_push_uses_stored_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fabricgate.models.cli import Credentials

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(
        sdk_api.auth,
        "load_credentials",
        lambda _reg: Credentials(
            registry="https://example.com/api/v1",
            token="stored-tok",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            scopes=["openid"],
        ),
    )

    result = sdk_api.push(tmp_path, registry="https://example.com/api/v1")
    assert result.name == "test-ns/blink"


def test_push_namespace_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project(tmp_path)

    captured: dict[str, str] = {}

    class _CapturingClient(_FakePushRegistryClient):
        def publish_version(self, namespace, design, version, files):
            captured["namespace"] = namespace
            captured["design"] = design
            return super().publish_version(namespace, design, version, files)

    _patch_all_rc(monkeypatch, _CapturingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    sdk_api.push(tmp_path, namespace="override-ns", token="tok")
    assert captured["namespace"] == "override-ns"
    assert captured["design"] == "blink"


def test_push_unauthenticated_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.push(tmp_path, registry="https://example.com/api/v1")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_push_invalid_design_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Design name without namespace slash should raise SDKError."""
    _write_push_project(tmp_path)
    # Overwrite index with invalid name (no namespace slash) — rejected by DesignIndex validation
    index_yaml = "\n".join(
        [
            "schema: fabricgate-index/v1",
            "name: blink-no-ns",
            "version: 1.0.0",
            "platforms:",
            "  - platform: xc7z020/pynq",
            "    digest: sha256:0000000000000000000000000000000000000000000000000000000000000000",
        ]
    )
    (tmp_path / "fabricgate-index.yaml").write_text(index_yaml)

    with pytest.raises(sdk_api.SDKError):
        sdk_api.push(tmp_path, token="tok")


def test_push_rejects_placeholder_digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project(tmp_path, placeholder_digest=True)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Placeholder digest"):
        sdk_api.push(tmp_path, token="tok-test")


def test_push_warns_on_placeholder_artifact_sha256(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Artifact with placeholder sha256 produces sha_warning in PushResult."""
    _write_push_project(tmp_path, placeholder_artifact_sha=True)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.push(tmp_path, token="tok-test")
    assert result.sha_warning is not None
    assert "placeholder" in result.sha_warning.lower() or "sha256" in result.sha_warning.lower()


def test_push_no_warning_when_skip_sha_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """skip_sha_check=True suppresses placeholder sha256 warning."""
    _write_push_project(tmp_path, placeholder_artifact_sha=True)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.push(tmp_path, token="tok-test", skip_sha_check=True)
    assert result.sha_warning is None


def test_is_placeholder_sha256() -> None:
    """_is_placeholder_sha256 identifies uniform-character 64-char digests."""
    from fabricgate.client.publisher import _is_placeholder_sha256

    assert _is_placeholder_sha256("a" * 64) is True
    assert _is_placeholder_sha256("f" * 64) is True
    assert _is_placeholder_sha256("abc" + "d" * 61) is False
    assert _is_placeholder_sha256("a" * 63) is False


# ===========================================================================
# CLI-PULL-002: dependency resolution, shell, deprecated, attestation
# ===========================================================================


class _FakeRegistryClientWithDeps:
    """Fake that returns dependencies and shell info for pull tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        bitstream = b"bitstream-data"
        hwh = b"<hwh/>"
        self.manifest_bytes = "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: test-ns/blink:1.0.0",
                "artifacts:",
                "  bitstream:",
                "    file: design.bit",
                f"    sha256: {hashlib.sha256(bitstream).hexdigest()}",
                "  hwh:",
                "    file: design.hwh",
                f"    sha256: {hashlib.sha256(hwh).hexdigest()}",
            ]
        ).encode("utf-8")
        self.dep_manifest_bytes = "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: dep-ns/dep-design:0.1.0",
                "artifacts:",
                "  bitstream:",
                "    file: dep.bit",
                f"    sha256: {hashlib.sha256(b'dep-bitstream').hexdigest()}",
                "  hwh:",
                "    file: dep.hwh",
                f"    sha256: {hashlib.sha256(b'dep-hwh').hexdigest()}",
            ]
        ).encode("utf-8")
        self.shell_manifest_bytes = "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: shell-ns/shell-design:2.0.0",
                "artifacts:",
                "  bitstream:",
                "    file: shell.bit",
                f"    sha256: {hashlib.sha256(b'shell-bitstream').hexdigest()}",
                "  hwh:",
                "    file: shell.hwh",
                f"    sha256: {hashlib.sha256(b'shell-hwh').hexdigest()}",
            ]
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_version(self, namespace, design, version):
        return VersionDetailResponse.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": f"{namespace}/{design}",
                "version": version,
                "summary": "Test design",
                "platforms": [
                    {
                        "platform": "xc7z020/pynq",
                        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
                "published_at": datetime(2026, 3, 17, tzinfo=UTC),
                "deprecated": False,
            }
        )

    def get_platform_manifest_bytes(self, namespace, design, *_args):
        if design == "dep-design":
            return self.dep_manifest_bytes
        if design == "shell-design":
            return self.shell_manifest_bytes
        return self.manifest_bytes

    def download_artifact(self, namespace, design, *_args):
        filename = _args[-1]
        if design == "dep-design":
            return b"dep-hwh" if filename.endswith(".hwh") else b"dep-bitstream"
        if design == "shell-design":
            return b"shell-hwh" if filename.endswith(".hwh") else b"shell-bitstream"
        if filename == "design.bit":
            return b"bitstream-data"
        return b"<hwh/>"

    def get_dependencies(self, *_args, **_kwargs):
        from fabricgate.models.api.responses import DependenciesResponse
        from fabricgate.models.platform_manifest import ResolvedDependency

        return DependenciesResponse(
            root="test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            dependencies=[
                ResolvedDependency(
                    name="dep-ns/dep-design",
                    resolved_version="0.1.0",
                    platform="xc7z020/pynq",
                    optional=False,
                    depth=1,
                    required_by="test-ns/blink",
                ),
            ],
        )

    def get_shell(self, *_args, **_kwargs):
        from fabricgate.models.api.responses import ShellInfo, ShellResponse

        return ShellResponse(
            shell=ShellInfo(
                name="shell-ns/shell-design",
                version="2.0.0",
                board="zcu104",
                runtime="pynq",
                bitstream_type="full",
                artifacts=[],
                pull_url="https://example.com/pull/shell",
            )
        )


class _FakeRegistryClientDeprecated(_FakeRegistryClientWithDeps):
    """Returns a deprecated version."""

    def get_version(self, namespace, design, version):
        return VersionDetailResponse.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": f"{namespace}/{design}",
                "version": version,
                "summary": "Old design",
                "platforms": [
                    {
                        "platform": "xc7z020/pynq",
                        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
                "published_at": datetime(2026, 3, 17, tzinfo=UTC),
                "deprecated": True,
                "deprecation_message": "Use newer version",
                "successor": "test-ns/blink:2.0.0",
            }
        )


class _FakeRegistryClientDepUnresolvable:
    """get_dependencies raises 409 DEPENDENCY_UNRESOLVABLE."""

    def __init__(self, *_args, **_kwargs):
        bitstream = b"bitstream-data"
        hwh = b"<hwh/>"
        self.manifest_bytes = "\n".join(
            [
                "schema: fabricgate-platform/v1",
                "runtime: pynq",
                "board: pynq-z2",
                "design_ref: test-ns/blink:1.0.0",
                "artifacts:",
                "  bitstream:",
                "    file: design.bit",
                f"    sha256: {hashlib.sha256(bitstream).hexdigest()}",
                "  hwh:",
                "    file: design.hwh",
                f"    sha256: {hashlib.sha256(hwh).hexdigest()}",
            ]
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_version(self, namespace, design, version):
        return VersionDetailResponse.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": f"{namespace}/{design}",
                "version": version,
                "platforms": [
                    {
                        "platform": "xc7z020/pynq",
                        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
                "published_at": datetime(2026, 3, 17, tzinfo=UTC),
            }
        )

    def get_platform_manifest_bytes(self, *_args):
        return self.manifest_bytes

    def download_artifact(self, *_args):
        filename = _args[-1]
        if filename == "design.bit":
            return b"bitstream-data"
        return b"<hwh/>"

    def get_dependencies(self, *_args, **_kwargs):
        from fabricgate.client.registry_client import RegistryError
        from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

        raise RegistryError(
            409,
            ErrorResponse(error=ErrorDetail(code="DEPENDENCY_UNRESOLVABLE", message="Cannot resolve deps")),
        )

    def get_shell(self, *_args, **_kwargs):
        from fabricgate.client.registry_client import RegistryError
        from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

        raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="No shell")))


class _FakeRegistryClientShellNotFound(_FakeRegistryClientDepUnresolvable):
    """get_shell raises SHELL_NOT_FOUND."""

    def get_dependencies(self, *_args, **_kwargs):
        from fabricgate.models.api.responses import DependenciesResponse

        return DependenciesResponse(root="test-ns/blink:1.0.0", platform="xc7z020/pynq", dependencies=[])

    def get_shell(self, *_args, **_kwargs):
        from fabricgate.client.registry_client import RegistryError
        from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

        raise RegistryError(
            409,
            ErrorResponse(error=ErrorDetail(code="SHELL_NOT_FOUND", message="Shell not found")),
        )


# --- Tests ---


def test_pull_resolves_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依存解決付きpullでdeps/にファイルが配置される。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert result.dependencies == ["dep-ns/dep-design:0.1.0"]
    dep_dir = tmp_path / "deps" / "dep-ns-dep-design-0.1.0"
    assert dep_dir.exists()
    assert (dep_dir / "manifest.yaml").exists()
    assert (dep_dir / "dep.bit").exists()


def test_pull_no_deps_skips_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """no_deps=Trueで依存解決がスキップされる。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_deps=True,
    )

    assert result.dependencies == []
    assert not (tmp_path / "deps").exists()


def test_pull_uses_stored_token_when_logged_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """token未指定でも保存済み認証情報があればRegistryClientへ渡す(API-KPI-001帰属)。"""
    captured: dict[str, Any] = {}

    class _CapturingClient(_FakeRegistryClientWithDeps):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["token"] = kwargs.get("token")
            super().__init__(*args, **kwargs)

    _patch_all_rc(monkeypatch, _CapturingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())

    sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_deps=True,
    )

    assert captured["token"] == "tok"


def test_pull_without_stored_token_stays_anonymous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """保存済み認証情報が無ければ従来どおり匿名pull(エラーにしない)。"""
    captured: dict[str, Any] = {}

    class _CapturingClient(_FakeRegistryClientWithDeps):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["token"] = kwargs.get("token")
            super().__init__(*args, **kwargs)

    _patch_all_rc(monkeypatch, _CapturingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_deps=True,
    )

    assert captured["token"] is None
    assert result.version == "1.0.0"


def test_pull_explicit_token_overrides_stored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """明示tokenが渡されたら保存済み認証情報は参照しない。"""
    captured: dict[str, Any] = {}
    auth_called = False

    class _CapturingClient(_FakeRegistryClientWithDeps):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["token"] = kwargs.get("token")
            super().__init__(*args, **kwargs)

    def _spy_load(*_a: Any, **_kw: Any):
        nonlocal auth_called
        auth_called = True
        return _token_creds()

    _patch_all_rc(monkeypatch, _CapturingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", _spy_load)

    sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_deps=True,
        token="explicit-tok",
    )

    assert captured["token"] == "explicit-tok"
    assert auth_called is False


def test_pull_credential_store_failure_stays_anonymous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """認証情報ストアの読込失敗はpullを妨げない(匿名継続)。"""
    captured: dict[str, Any] = {}

    class _CapturingClient(_FakeRegistryClientWithDeps):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["token"] = kwargs.get("token")
            super().__init__(*args, **kwargs)

    def _broken_load(*_a: Any, **_kw: Any):
        raise OSError("credential store unreadable")

    _patch_all_rc(monkeypatch, _CapturingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", _broken_load)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_deps=True,
    )

    assert captured["token"] is None
    assert result.version == "1.0.0"


def test_pull_credential_resolution_programmer_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """認証情報解決中のプログラミングエラー(非OSError/ValueError)は透過する。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    def _buggy_load(*_a: Any, **_kw: Any):
        raise TypeError("programmer error in credential resolution")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", _buggy_load)

    with pytest.raises(TypeError, match="programmer error"):
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            output=tmp_path,
            cache_dir=tmp_path / "cache",
            no_deps=True,
        )


def test_pull_deps_only_skips_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """deps_only=Trueでルートデザインがダウンロードされない。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        deps_only=True,
    )

    # Root artifacts not downloaded
    assert result.artifacts == []
    assert not (tmp_path / "design.bit").exists()
    # Dependencies should still be downloaded
    assert result.dependencies == ["dep-ns/dep-design:0.1.0"]


def test_pull_shell_auto_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """partial bitstream時にshellが自動ダウンロードされる。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert result.shell == "shell-ns/shell-design:2.0.0"
    shell_dir = tmp_path / "shell" / "shell-ns-shell-design-2.0.0"
    assert shell_dir.exists()
    assert (shell_dir / "manifest.yaml").exists()
    assert (shell_dir / "shell.bit").exists()


def test_pull_no_shell_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """no_shell=Trueでshellスキップ。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
        no_shell=True,
    )

    assert result.shell is None
    assert not (tmp_path / "shell").exists()


def test_pull_deprecated_version_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """deprecated版のpullでdeprecated_warningが設定される。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientDeprecated)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        platform="xc7z020/pynq",
        output=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert result.deprecated_warning is not None
    assert "deprecated" in result.deprecated_warning
    assert "test-ns/blink:2.0.0" in result.deprecated_warning
    assert "Use newer version" in result.deprecated_warning


def test_pull_dependency_unresolvable_exit_5(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """409 DEPENDENCY_UNRESOLVABLE応答でexit code 5。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientDepUnresolvable)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            output=tmp_path,
            cache_dir=tmp_path / "cache",
        )

    assert exc_info.value.code == ExitKind.UNRESOLVABLE


def test_pull_shell_not_found_exit_6(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SHELL_NOT_FOUND応答でexit code 6。"""
    _patch_all_rc(monkeypatch, _FakeRegistryClientShellNotFound)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            output=tmp_path,
            cache_dir=tmp_path / "cache",
        )

    assert exc_info.value.code == ExitKind.SHELL_NOT_FOUND


def test_pull_no_deps_and_deps_only_mutual_exclusion(
    tmp_path: Path,
) -> None:
    """--no-deps and --deps-only are mutually exclusive."""
    with pytest.raises(sdk_api.SDKError, match="mutually exclusive"):
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            output=tmp_path,
            no_deps=True,
            deps_only=True,
        )


# ===========================================================================
# CLI-TOKEN-001: token SDK functions
# ===========================================================================


def _token_creds():
    from fabricgate.models.cli import Credentials

    return Credentials(
        registry="http://test",
        token="tok",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        scopes=["admin"],
    )


def test_token_create_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """token_createがTokenCreateResultを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _FakeRegistryClient)

    result = sdk_api.token_create(name="ci-key", scopes="public:read", registry="http://test")
    assert result.id == 42
    assert result.name == "ci-key"
    assert result.key == "fgk_abc123secrettoken"
    assert result.scopes == ["public:read"]


def test_token_create_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.token_create(name="ci-key", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_token_create_scope_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """SCOPE_NOT_ALLOWED → SDKError exit_code=2。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ScopeErrorClient(_FakeRegistryClient):
        def create_api_key(self, *_a, **_kw):
            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="SCOPE_NOT_ALLOWED", message="Scope not allowed")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _ScopeErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_create(name="ci-key", scopes="admin", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_token_create_key_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 rate limit → SDKError exit_code=3。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _LimitClient(_FakeRegistryClient):
        def create_api_key(self, *_a, **_kw):
            raise RegistryError(
                429,
                ErrorResponse(error=ErrorDetail(code="KEY_LIMIT_EXCEEDED", message="Too many keys")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _LimitClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_create(name="ci-key", registry="http://test")
    assert exc_info.value.code == ExitKind.INVALID


def test_token_list_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """token_listがTokenInfoのリストを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _FakeRegistryClient)

    result = sdk_api.token_list(registry="http://test")
    assert len(result) == 1
    assert result[0].id == 1
    assert result[0].name == "key-alpha"
    assert result[0].scopes == ["public:read"]


def test_token_revoke_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """token_revokeの正常系。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _FakeRegistryClient)

    # Should not raise
    sdk_api.token_revoke(42, registry="http://test")


def test_token_revoke_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """存在しないキーでSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _FakeRegistryClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_revoke(999, registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_parse_expires_relative() -> None:
    """90d → ISO datetimeになる。"""
    from fabricgate.sdk.auth import _parse_expires

    result = _parse_expires("90d")
    assert result is not None
    # Should be a valid ISO 8601 string
    from datetime import datetime as _dt

    dt = _dt.fromisoformat(result)
    assert dt.tzinfo is not None


def test_parse_expires_iso() -> None:
    """ISO文字列はそのまま返る。"""
    from fabricgate.sdk.auth import _parse_expires

    iso_str = "2027-06-01T00:00:00+00:00"
    assert _parse_expires(iso_str) == iso_str


def test_parse_expires_none() -> None:
    """NoneはNoneを返す。"""
    from fabricgate.sdk.auth import _parse_expires

    assert _parse_expires(None) is None


def test_parse_expires_exceeds_limit() -> None:
    """3651d → SDKError (3650日上限超過)。"""
    from fabricgate.sdk.auth import _parse_expires

    with pytest.raises(sdk_api.SDKError, match="3650"):
        _parse_expires("3651d")


def test_token_exit_code_fallthrough_401() -> None:
    """401 + 非SCOPE_NOT_ALLOWED → return 1 のフォールスルー。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import ExitKind, _registry_error_kind

    exc = RegistryError(401, ErrorResponse(error=ErrorDetail(code="UNAUTHORIZED", message="401")))
    assert _registry_error_kind(exc) == ExitKind.PERMISSION


def test_token_exit_code_server_error_500() -> None:
    """500 → return 4。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import ExitKind, _registry_error_kind

    exc = RegistryError(500, ErrorResponse(error=ErrorDetail(code="INTERNAL_ERROR", message="server error")))
    assert _registry_error_kind(exc) == ExitKind.INFRA


def test_exitkind_is_failurekind_alias() -> None:
    from fabricgate.client.errors import FailureKind
    from fabricgate.sdk._helpers import ExitKind

    assert ExitKind is FailureKind


def test_registry_error_kind_delegates_to_property() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(404, ErrorResponse(error=ErrorDetail(code="X", message="m")))
    assert _registry_error_kind(exc) is exc.kind


def test_token_create_empty_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    """カンマのみのscopesはSDKError (少なくとも1スコープ必要)。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())

    with pytest.raises(sdk_api.SDKError, match="scope"):
        sdk_api.token_create(name="ci-key", scopes=",", registry="http://test")


def test_token_create_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_api_key がa transport NetworkErrorを投げるとSDKError exit_code=4になる。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def create_api_key(self, *_a: Any, **_kw: Any) -> None:
            raise NetworkError("Network error: connection refused")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_create(name="ci-key", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_token_list_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.token_list(registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_token_list_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_api_keys RegistryError → SDKError exit_code=1。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrorClient(_FakeRegistryClient):
        def list_api_keys(self) -> None:
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _ErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_list(registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_token_list_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_api_keys a transport NetworkError → SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def list_api_keys(self) -> None:
            raise NetworkError("Network error: connection refused")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_list(registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_token_revoke_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.token_revoke(42, registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_token_revoke_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_api_key a transport NetworkError → SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_FakeRegistryClient):
        def delete_api_key(self, key_id: int) -> None:
            raise NetworkError("Network error: connection refused")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _token_creds())
    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.token_revoke(42, registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


# ===========================================================================
# CLI-WEBHOOK-001: webhook SDK functions
# ===========================================================================


def _webhook_creds():
    from fabricgate.models.cli import Credentials

    return Credentials(
        registry="http://test",
        token="tok",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        scopes=["admin"],
    )


class _WebhookFakeClient(_FakeRegistryClient):
    """Extends _FakeRegistryClient with webhook methods."""

    def create_webhook(self, namespace, url, events, design=None):
        from fabricgate.models.api.responses import WebhookCreateResponse

        return WebhookCreateResponse(
            id=10,
            url=url,
            events=events,
            design=design,
            secret="whsec_abcdef1234567890",
            status="active",
            created_at=datetime(2026, 3, 29, tzinfo=UTC),
        )

    def list_webhooks(self, namespace):
        from fabricgate.models.api.responses import WebhookInfo, WebhookListResponse

        return WebhookListResponse(
            webhooks=[
                WebhookInfo(
                    id=10,
                    url="https://example.com/hook",
                    events=["design.published"],
                    status="active",
                    last_delivered_at=datetime(2026, 3, 28, tzinfo=UTC),
                    created_at=datetime(2026, 3, 1, tzinfo=UTC),
                ),
            ]
        )

    def delete_webhook(self, namespace, webhook_id):
        if webhook_id == 999:
            from fabricgate.client.registry_client import RegistryError
            from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Webhook not found")),
            )

    def test_webhook(self, namespace, webhook_id):
        from fabricgate.models.api.responses import WebhookTestResponse

        return WebhookTestResponse(delivered=True, status_code=200, duration_ms=120)

    def list_webhook_deliveries(self, namespace, webhook_id, limit=None):
        from fabricgate.models.api.responses import (
            WebhookDeliveriesResponse,
            WebhookDelivery,
        )

        items = [
            WebhookDelivery(
                id="d-001",
                event="design.published",
                status_code=200,
                duration_ms=95,
                delivered_at=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            ),
            WebhookDelivery(
                id="d-002",
                event="design.yanked",
                status_code=502,
                duration_ms=5000,
                delivered_at=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
                redelivery=True,
            ),
        ]
        if limit is not None:
            items = items[:limit]
        return WebhookDeliveriesResponse(deliveries=items)


def test_webhook_create_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_createがWebhookCreateResultを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    result = sdk_api.webhook_create(
        namespace="myns",
        url="https://example.com/hook",
        events="design.published,design.yanked",
        registry="http://test",
    )
    assert result.id == 10
    assert result.url == "https://example.com/hook"
    assert result.events == ["design.published", "design.yanked"]
    assert result.secret == "whsec_abcdef1234567890"
    assert result.status == "active"


def test_webhook_create_http_url_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """http:// URLはexit_code=2で拒否される。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())

    with pytest.raises(sdk_api.SDKError, match="HTTPS") as exc_info:
        sdk_api.webhook_create(
            namespace="myns",
            url="http://example.com/hook",
            events="design.published",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.INVALID


def test_webhook_create_empty_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """空のeventsでSDKError。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())

    with pytest.raises(sdk_api.SDKError, match="event"):
        sdk_api.webhook_create(
            namespace="myns",
            url="https://example.com/hook",
            events="",
            registry="http://test",
        )


def test_webhook_create_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.webhook_create(
            namespace="myns",
            url="https://example.com/hook",
            events="design.published",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_create_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEBHOOK_LIMIT_EXCEEDED → SDKError exit_code=3。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _LimitClient(_WebhookFakeClient):
        def create_webhook(self, *_a, **_kw):
            raise RegistryError(
                429,
                ErrorResponse(error=ErrorDetail(code="WEBHOOK_LIMIT_EXCEEDED", message="Limit exceeded")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _LimitClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.webhook_create(
            namespace="myns",
            url="https://example.com/hook",
            events="design.published",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.INVALID


def test_webhook_list_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_listがWebhookItemのリストを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    result = sdk_api.webhook_list(namespace="myns", registry="http://test")
    assert len(result) == 1
    assert result[0].id == 10
    assert result[0].url == "https://example.com/hook"
    assert result[0].events == ["design.published"]


def test_webhook_delete_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_deleteの正常系。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    # Should not raise
    sdk_api.webhook_delete(10, namespace="myns", registry="http://test")


def test_webhook_test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_testがWebhookTestResultを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    result = sdk_api.webhook_test(10, namespace="myns", registry="http://test")
    assert result.delivered is True
    assert result.status_code == 200
    assert result.duration_ms == 120


def test_webhook_deliveries_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_deliveriesがWebhookDeliveryItemのリストを返す。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    result = sdk_api.webhook_deliveries(10, namespace="myns", registry="http://test")
    assert len(result) == 2
    assert result[0].id == "d-001"
    assert result[0].event == "design.published"
    assert result[1].id == "d-002"
    assert result[1].redelivery is True


def test_webhook_deliveries_with_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """limitを指定すると結果が制限される。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    result = sdk_api.webhook_deliveries(10, namespace="myns", limit=1, registry="http://test")
    assert len(result) == 1
    assert result[0].id == "d-001"


# --- webhook error path coverage ---


def test_webhook_create_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """a transport NetworkErrorがSDKError exit_code=4になる。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrClient(_WebhookFakeClient):
        def create_webhook(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _NetworkErrClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.webhook_create(
            namespace="myns",
            url="https://example.com/hook",
            events="design.published",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.INFRA


def test_webhook_list_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_list: 未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.webhook_list(namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_list_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_list: RegistryError→SDKError。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrClient(_WebhookFakeClient):
        def list_webhooks(self, *_a, **_kw):
            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="FORBIDDEN", message="Forbidden")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _ErrClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.webhook_list(namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_list_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_list: a transport NetworkError→SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrClient(_WebhookFakeClient):
        def list_webhooks(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _NetworkErrClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.webhook_list(namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_webhook_delete_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_delete: 未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.webhook_delete(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_delete_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_delete: RegistryError→SDKError exit_code=1 (404)。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _WebhookFakeClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.webhook_delete(999, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_webhook_delete_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_delete: a transport NetworkError→SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrClient(_WebhookFakeClient):
        def delete_webhook(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _NetworkErrClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.webhook_delete(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_webhook_test_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_test: 未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.webhook_test(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_test_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_test: RegistryError→SDKError exit_code=1 (404)。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrClient(_WebhookFakeClient):
        def test_webhook(self, *_a, **_kw):
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Webhook not found")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _ErrClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.webhook_test(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_webhook_test_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_test: a transport NetworkError→SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrClient(_WebhookFakeClient):
        def test_webhook(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _NetworkErrClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.webhook_test(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_webhook_deliveries_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_deliveries: 未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.webhook_deliveries(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_webhook_deliveries_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_deliveries: RegistryError→SDKError。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrClient(_WebhookFakeClient):
        def list_webhook_deliveries(self, *_a, **_kw):
            raise RegistryError(
                429,
                ErrorResponse(error=ErrorDetail(code="RATE_LIMITED", message="rate limited")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _ErrClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.webhook_deliveries(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.INVALID


def test_webhook_deliveries_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """webhook_deliveries: a transport NetworkError→SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrClient(_WebhookFakeClient):
        def list_webhook_deliveries(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _webhook_creds())
    _patch_all_rc(monkeypatch, _NetworkErrClient)

    with pytest.raises(sdk_api.SDKError, match="Network error") as exc_info:
        sdk_api.webhook_deliveries(10, namespace="myns", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_webhook_exit_code_401() -> None:
    """_webhook_exit_code: 401→1。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    exc = RegistryError(401, ErrorResponse(error=ErrorDetail(code="UNAUTHORIZED", message="unauth")))
    from fabricgate.sdk._helpers import _registry_error_kind

    assert _registry_error_kind(exc) == ExitKind.PERMISSION


def test_webhook_exit_code_404() -> None:
    """_webhook_exit_code: 404→1。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    exc = RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))
    from fabricgate.sdk._helpers import _registry_error_kind

    assert _registry_error_kind(exc) == ExitKind.NOT_FOUND


def test_webhook_exit_code_429_rate_limited() -> None:
    """_webhook_exit_code: 429 non-limit-exceeded→3。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    exc = RegistryError(
        429,
        ErrorResponse(error=ErrorDetail(code="RATE_LIMITED", message="rate limited")),
    )
    from fabricgate.sdk._helpers import _registry_error_kind

    assert _registry_error_kind(exc) == ExitKind.INVALID


def test_webhook_exit_code_500() -> None:
    """_webhook_exit_code: 500→4。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    exc = RegistryError(500, ErrorResponse(error=ErrorDetail(code="INTERNAL", message="internal")))
    from fabricgate.sdk._helpers import _registry_error_kind

    assert _registry_error_kind(exc) == ExitKind.INFRA


def test_webhook_exit_code_url_insecure() -> None:
    """_webhook_exit_code: WEBHOOK_URL_INSECURE→2。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    exc = RegistryError(
        400,
        ErrorResponse(error=ErrorDetail(code="WEBHOOK_URL_INSECURE", message="insecure")),
    )
    from fabricgate.sdk._helpers import _registry_error_kind

    assert _registry_error_kind(exc) == ExitKind.INVALID


# ===========================================================================
# CLI-YANK-001: yank SDK function
# ===========================================================================


def _yank_creds():
    from fabricgate.models.cli import Credentials

    return Credentials(
        registry="http://test",
        token="tok",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        scopes=["admin"],
    )


class _YankFakeClient(_FakeRegistryClient):
    """Extends _FakeRegistryClient with yank_version method."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.yank_calls: list[tuple[str, str, str, str]] = []

    def yank_version(self, namespace, design, version, reason=""):
        from fabricgate.models.api.responses import YankResponse

        self.yank_calls.append((namespace, design, version, reason))
        return YankResponse(
            name=f"{namespace}/{design}",
            version=version,
            yanked=True,
            yanked_reason=reason,
        )

    def deprecate_version(self, namespace, design, version, message="", successor=None):
        from fabricgate.models.api.responses import DeprecateResponse

        return DeprecateResponse(
            name=f"{namespace}/{design}",
            version=version,
            deprecated=True,
            deprecation_message=message,
            successor=successor,
        )

    def undeprecate_version(self, namespace, design, version):
        from fabricgate.models.api.responses import DeprecateResponse

        return DeprecateResponse(
            name=f"{namespace}/{design}",
            version=version,
            deprecated=False,
            deprecation_message=None,
            successor=None,
        )


def test_yank_single_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """design_refに:があると単一バージョンyankeされる。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    results = sdk_api.yank("alice/counter:1.0.0", reason="bug", registry="http://test")
    assert len(results) == 1
    assert results[0].name == "alice/counter"
    assert results[0].version == "1.0.0"
    assert results[0].yanked is True
    assert results[0].yanked_reason == "bug"


def test_yank_multi_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """design_refに:なし + versionsリストで複数バージョンyank。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    results = sdk_api.yank("alice/counter", ["0.9.0", "1.0.0"], reason="cve", registry="http://test")
    assert len(results) == 2
    assert results[0].version == "0.9.0"
    assert results[1].version == "1.0.0"


def test_yank_no_versions_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """バージョン未指定でSDKError。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())

    with pytest.raises(sdk_api.SDKError, match="No versions specified"):
        sdk_api.yank("alice/counter", registry="http://test")


def test_yank_max_versions_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """51バージョンでSDKError。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())

    versions = [f"0.0.{i}" for i in range(51)]
    with pytest.raises(sdk_api.SDKError, match="Maximum 50"):
        sdk_api.yank("alice/counter", versions, registry="http://test")


def test_yank_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """未認証時にSDKError exit_code=1。"""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.yank("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_yank_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """403 → SDKError exit_code=2。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _PermClient(_YankFakeClient):
        def yank_version(self, *_a, **_kw):
            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="FORBIDDEN", message="Permission denied")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _PermClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.yank("alice/counter:1.0.0", reason="bug", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_yank_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 → SDKError exit_code=1。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_YankFakeClient):
        def yank_version(self, *_a, **_kw):
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Version not found")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.yank("alice/counter:1.0.0", reason="bug", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


# ===========================================================================
# CLI-DEPRECATE-001: deprecate SDK function
# ===========================================================================


def test_deprecate_single_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    results = sdk_api.deprecate(
        "alice/counter:1.0.0",
        message="Upgrade to 2.0.0",
        successor="alice/counter:2.0.0",
        registry="http://test",
    )
    assert len(results) == 1
    assert results[0].deprecated is True
    assert results[0].deprecation_message == "Upgrade to 2.0.0"
    assert results[0].successor == "alice/counter:2.0.0"


def test_undeprecate_single_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    results = sdk_api.undeprecate("alice/counter:1.0.0", registry="http://test")
    assert len(results) == 1
    assert results[0].deprecated is False


def test_deprecate_requires_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())

    with pytest.raises(sdk_api.SDKError, match="--message is required"):
        sdk_api.deprecate("alice/counter:1.0.0", message="", registry="http://test")


def test_deprecate_invalid_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())

    with pytest.raises(sdk_api.SDKError, match="Invalid version"):
        sdk_api.deprecate("alice/counter", ["../bad"], message="legacy", registry="http://test")


def test_deprecate_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _PermClient(_YankFakeClient):
        def deprecate_version(self, *_a, **_kw):
            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="FORBIDDEN", message="Permission denied")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _PermClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.deprecate("alice/counter:1.0.0", message="legacy", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_undeprecate_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_YankFakeClient):
        def undeprecate_version(self, *_a, **_kw):
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Version not found")),
            )

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.undeprecate("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_undeprecate_invalid_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that undeprecate validates version format before API call."""
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    with pytest.raises(sdk_api.SDKError, match="Invalid version"):
        sdk_api.undeprecate("alice/counter", ["../malicious"], registry="http://test")


# ===========================================================================
# CLI-LICENSE-001: license_check SDK tests
# ===========================================================================


class _LicenseCheckFakeClient:
    """Fake client for license_check tests."""

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def license_check(self, namespace, design, version, tool=None, edition=None):
        return LicenseCheckResponse(
            design=f"{namespace}/{design}",
            version=version,
            tool_requirements=[
                ToolRequirement(tool="vivado", min_version="2023.1", edition="enterprise", required=True, note="Synth"),
            ],
            check=None,
        )


class _LicenseCheckWithToolFakeClient(_LicenseCheckFakeClient):
    def license_check(self, namespace, design, version, tool=None, edition=None):
        return LicenseCheckResponse(
            design=f"{namespace}/{design}",
            version=version,
            tool_requirements=[
                ToolRequirement(tool="vivado", min_version="2023.1", edition="enterprise", required=True),
            ],
            check=ApiLicenseCheckResult(
                tool="vivado",
                edition="enterprise",
                meets_requirements=True,
                notes=["Vivado 2023.2 >= 2023.1"],
            ),
        )


def test_license_check_list_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool/edition未指定 → tool_requirementsのみ返す。"""
    _patch_all_rc(monkeypatch, _LicenseCheckFakeClient)

    result = sdk_api.license_check("alice/counter:1.0.0", registry="http://test")

    assert isinstance(result, LicenseCheckInfo)
    assert result.design == "alice/counter"
    assert result.version == "1.0.0"
    assert len(result.tool_requirements) == 1
    assert result.tool_requirements[0].tool == "vivado"
    assert result.check is None


def test_license_check_with_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool/edition指定 → checkフィールドが返る。"""
    _patch_all_rc(monkeypatch, _LicenseCheckWithToolFakeClient)

    result = sdk_api.license_check(
        "alice/counter:1.0.0",
        tool=["vivado"],
        edition="enterprise",
        registry="http://test",
    )

    assert result.check is not None
    assert result.check.tool == "vivado"
    assert result.check.meets_requirements is True
    assert "Vivado 2023.2 >= 2023.1" in result.check.notes


def test_license_check_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 RegistryError → SDKError exit_code=1。"""
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_LicenseCheckFakeClient):
        def license_check(self, *_a, **_kw):
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Design not found")),
            )

    _patch_all_rc(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.license_check("alice/missing:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_license_check_no_auth_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """license_checkはauth.load_credentialsを呼ばない(公開エンドポイント)。"""
    auth_called = False

    original_load = sdk_api.auth.load_credentials

    def _spy_load(*args, **kwargs):
        nonlocal auth_called
        auth_called = True
        return original_load(*args, **kwargs)

    monkeypatch.setattr(sdk_api.auth, "load_credentials", _spy_load)
    _patch_all_rc(monkeypatch, _LicenseCheckFakeClient)

    sdk_api.license_check("alice/counter:1.0.0", registry="http://test")

    assert auth_called is False


def test_license_check_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """a transport NetworkError → SDKError exit_code=4。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_LicenseCheckFakeClient):
        def license_check(self, *_a, **_kw):
            raise NetworkError("Network error: Connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.license_check("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA
    assert "Network error" in str(exc_info.value)


# ===========================================================================
# CLI-DIFF-001: diff SDK tests
# ===========================================================================


class _DiffFakeClient:
    """Fake client for diff tests."""

    last_call: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_version_diff(self, namespace, design, version, base, platform=None):
        type(self).last_call = {
            "namespace": namespace,
            "design": design,
            "version": version,
            "base": base,
            "platform": platform,
        }
        return VersionDiffResponse(
            base=base,
            head=version,
            summary=VersionDiffSummary(platforms_changed=["xczu7ev/pynq"]),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="bitstream_type", base=None, head="partial")],
                )
            ],
        )


def test_diff_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _DiffFakeClient)

    result = sdk_api.diff(
        "alice/counter:2.0.0",
        base="alice/counter:1.0.0",
        platform="xczu7ev/pynq",
        registry="http://test",
    )

    assert result.base == "1.0.0"
    assert result.head == "2.0.0"
    assert result.summary.platforms_changed == ["xczu7ev/pynq"]
    assert _DiffFakeClient.last_call == {
        "namespace": "alice",
        "design": "counter",
        "version": "2.0.0",
        "base": "1.0.0",
        "platform": "xczu7ev/pynq",
    }


def test_diff_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_DiffFakeClient):
        def get_version_diff(self, *_a, **_kw):
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Design not found")),
            )

    _patch_all_rc(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.diff("alice/missing:2.0.0", base="1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_diff_no_auth_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_called = False

    original_load = sdk_api.auth.load_credentials

    def _spy_load(*args, **kwargs):
        nonlocal auth_called
        auth_called = True
        return original_load(*args, **kwargs)

    monkeypatch.setattr(sdk_api.auth, "load_credentials", _spy_load)
    _patch_all_rc(monkeypatch, _DiffFakeClient)

    sdk_api.diff("alice/counter:2.0.0", base="1.0.0", registry="http://test")

    assert auth_called is False


def test_diff_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_DiffFakeClient):
        def get_version_diff(self, *_a, **_kw):
            raise NetworkError("Network error: Connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.diff("alice/counter:2.0.0", base="1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA
    assert "Network error" in str(exc_info.value)


# ===========================================================================
# CLI-STATS-001: stats SDK tests
# ===========================================================================


class _StatsFakeClient:
    last_call: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_design_stats(self, namespace, design, *, period=None, from_date=None, to_date=None):
        type(self).last_call = {
            "method": "get_design_stats",
            "namespace": namespace,
            "design": design,
            "period": period,
            "from_date": from_date,
            "to_date": to_date,
        }
        return DesignStatsResponse.model_validate(
            {
                "name": f"{namespace}/{design}",
                "total_downloads": 150,
                "period": period or "daily",
                "series": [
                    {"date": date(2026, 3, 25), "downloads": 10},
                    {"date": date(2026, 3, 26), "downloads": 20},
                    {"date": date(2026, 3, 27), "downloads": 30},
                ],
            }
        )

    def get_version_stats(self, namespace, design, version, *, period=None, from_date=None, to_date=None):
        type(self).last_call = {
            "method": "get_version_stats",
            "namespace": namespace,
            "design": design,
            "version": version,
            "period": period,
            "from_date": from_date,
            "to_date": to_date,
        }
        return VersionStatsResponse.model_validate(
            {
                "name": f"{namespace}/{design}",
                "version": version,
                "total_downloads": 75,
                "period": period or "daily",
                "series": [
                    {"date": date(2026, 3, 25), "downloads": 15},
                    {"date": date(2026, 3, 26), "downloads": 25},
                    {"date": date(2026, 3, 27), "downloads": 35},
                ],
            }
        )

    def get_namespace_stats(self, namespace):
        type(self).last_call = {
            "method": "get_namespace_stats",
            "namespace": namespace,
        }
        return NamespaceStatsResponse.model_validate(
            {
                "namespace": namespace,
                "total_downloads": 1000,
                "top_designs": [
                    {"name": f"{namespace}/blink", "total_downloads": 600},
                    {"name": f"{namespace}/uart", "total_downloads": 400},
                ],
                "period_downloads": {"last_7d": 90, "last_30d": 300},
            }
        )


def test_stats_design(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _StatsFakeClient)

    result = sdk_api.stats(
        design_ref="alice/blink",
        period="daily",
        from_date="2026-03-01",
        to_date="2026-03-31",
        registry="http://test",
    )

    assert isinstance(result, DesignStatsInfo)
    assert result.name == "alice/blink"
    assert result.total_downloads == 150
    assert result.last_7d == 60
    assert result.last_30d == 60
    assert _StatsFakeClient.last_call == {
        "method": "get_design_stats",
        "namespace": "alice",
        "design": "blink",
        "period": "daily",
        "from_date": "2026-03-01",
        "to_date": "2026-03-31",
    }


def test_stats_design_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _StatsFakeClient)

    result = sdk_api.stats(design_ref="alice/blink", version="1.2.0", period="weekly", registry="http://test")

    assert isinstance(result, DesignStatsInfo)
    assert result.version == "1.2.0"
    assert result.total_downloads == 75
    assert _StatsFakeClient.last_call == {
        "method": "get_version_stats",
        "namespace": "alice",
        "design": "blink",
        "version": "1.2.0",
        "period": "weekly",
        "from_date": None,
        "to_date": None,
    }


def test_stats_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _StatsFakeClient)

    result = sdk_api.stats(namespace="alice", registry="http://test")

    assert isinstance(result, NamespaceStatsInfo)
    assert result.namespace == "alice"
    assert result.last_7d == 90
    assert result.last_30d == 300


def test_stats_requires_single_target() -> None:
    with pytest.raises(sdk_api.SDKError, match="Either design_ref or namespace"):
        sdk_api.stats()
    with pytest.raises(sdk_api.SDKError, match="either design_ref or namespace"):
        sdk_api.stats(design_ref="alice/blink", namespace="alice")


def test_stats_version_conflict() -> None:
    with pytest.raises(sdk_api.SDKError, match="both design_ref and --version"):
        sdk_api.stats(design_ref="alice/blink:1.0.0", version="1.2.0")


def test_stats_namespace_validation() -> None:
    with pytest.raises(sdk_api.SDKError, match="Invalid namespace"):
        sdk_api.stats(namespace="Alice")


def test_stats_date_validation() -> None:
    with pytest.raises(sdk_api.SDKError, match="Invalid from_date"):
        sdk_api.stats(design_ref="alice/blink", from_date="2026/03/01")

    with pytest.raises(sdk_api.SDKError, match="from_date must be <= to_date"):
        sdk_api.stats(design_ref="alice/blink", from_date="2026-03-31", to_date="2026-03-01")


def test_stats_permission_error_maps_to_exit_code_2(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ForbiddenClient(_StatsFakeClient):
        def get_namespace_stats(self, namespace):
            raise RegistryError(
                403,
                ErrorResponse(error=ErrorDetail(code="STATS_PRIVATE", message="forbidden")),
            )

    _patch_all_rc(monkeypatch, _ForbiddenClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.stats(namespace="private-ns", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_stats_not_found_maps_to_exit_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_StatsFakeClient):
        def get_design_stats(self, *_args, **_kwargs):
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="missing")))

    _patch_all_rc(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.stats(design_ref="alice/missing", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


# ---------------------------------------------------------------------------
# quota (CLI-QUOTA-001)
# ---------------------------------------------------------------------------


class _QuotaFakeClient:
    last_namespace: str | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_namespace_quota(self, namespace: str) -> QuotaResponse:
        type(self).last_namespace = namespace
        return QuotaResponse.model_validate(
            {
                "namespace": namespace,
                "storage": {"used_bytes": 1024, "limit_bytes": 10_240, "used_percent": 10.0},
                "versions_per_design": {"limit": 100},
                "designs": {"used": 4, "limit": 200},
                "file_size_limit_bytes": 524_288_000,
            }
        )


def test_quota_explicit_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_rc(monkeypatch, _QuotaFakeClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.quota(namespace="alice", registry="http://test")

    assert result.namespace == "alice"
    assert _QuotaFakeClient.last_namespace == "alice"


def test_quota_default_namespace_from_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.models.cli import Credentials

    _patch_all_rc(monkeypatch, _QuotaFakeClient)
    monkeypatch.setattr(
        sdk_api.auth,
        "load_credentials",
        lambda _reg: Credentials(
            registry="http://test",
            token="tok",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            scopes=["openid", "ns:alice:read", "ns:alice:write"],
        ),
    )

    result = sdk_api.quota(registry="http://test")

    assert result.namespace == "alice"
    assert _QuotaFakeClient.last_namespace == "alice"


def test_quota_permission_error_maps_to_exit_code_2(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ForbiddenClient(_QuotaFakeClient):
        def get_namespace_quota(self, namespace: str) -> QuotaResponse:
            raise RegistryError(403, ErrorResponse(error=ErrorDetail(code="FORBIDDEN", message="forbidden")))

    _patch_all_rc(monkeypatch, _ForbiddenClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.quota(namespace="private", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_quota_network_error_maps_to_exit_code_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_namespace_quota が a transport NetworkError を投げると SDKError code=INFRA (exit 4)。"""
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_QuotaFakeClient):
        def get_namespace_quota(self, namespace: str) -> QuotaResponse:
            raise NetworkError("Network error: connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.quota(namespace="alice", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_quota_requires_namespace_or_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.quota(registry="http://test")
    assert exc_info.value.code == ExitKind.GENERIC


# ===========================================================================
# list_remote (fabricgate list --remote)
# ===========================================================================


def _design_summary(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "latest_version": "1.0.0",
        "summary": None,
        "platforms": ["xczu7ev/pynq", "xczu7ev/linux-fpgamgr"],
        "tags": [],
        "updated_at": "2026-03-17T00:00:00Z",
    }


class _ListRemoteFakeClient:
    calls: ClassVar[list[dict[str, Any]]] = []
    pages: ClassVar[list[list[dict[str, Any]]]] = [[_design_summary("alice/blink")]]

    def __init__(self, *_args, **kwargs) -> None:
        type(self).calls.append({"init": kwargs})

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def search_designs(self, **kwargs: Any) -> SearchResponse:
        type(self).calls.append(kwargs)
        page = kwargs["page"]
        total = sum(len(p) for p in type(self).pages)
        designs = type(self).pages[page - 1] if page - 1 < len(type(self).pages) else []
        body = {"designs": designs, "total": total, "page": page, "per_page": kwargs["per_page"]}
        return SearchResponse.model_validate_json(json.dumps(body))


def test_list_remote_explicit_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _ListRemoteFakeClient.calls = []
    _ListRemoteFakeClient.pages = [[_design_summary("alice/blink")]]
    _patch_all_rc(monkeypatch, _ListRemoteFakeClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.list_remote(namespace="alice", registry="http://test")

    assert [d.name for d in result] == ["alice/blink"]
    assert result[0].latest_version == "1.0.0"
    assert _ListRemoteFakeClient.calls[1]["namespace"] == "alice"


def test_list_remote_pages_through_all_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _ListRemoteFakeClient.calls = []
    first_page = [_design_summary(f"alice/d{i}") for i in range(100)]
    _ListRemoteFakeClient.pages = [first_page, [_design_summary("alice/last")]]
    _patch_all_rc(monkeypatch, _ListRemoteFakeClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.list_remote(namespace="alice", registry="http://test")

    assert len(result) == 101
    assert result[-1].name == "alice/last"
    assert [c["page"] for c in _ListRemoteFakeClient.calls[1:]] == [1, 2]


def test_list_remote_default_namespace_from_scopes_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.models.cli import Credentials

    _ListRemoteFakeClient.calls = []
    _ListRemoteFakeClient.pages = [[_design_summary("alice/blink")]]
    _patch_all_rc(monkeypatch, _ListRemoteFakeClient)
    monkeypatch.setattr(
        sdk_api.auth,
        "load_credentials",
        lambda _reg: Credentials(
            registry="http://test",
            token="tok",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            scopes=["openid", "ns:alice:read", "ns:alice:write"],
        ),
    )

    sdk_api.list_remote(registry="http://test")

    assert _ListRemoteFakeClient.calls[0]["init"]["token"] == "tok"
    assert _ListRemoteFakeClient.calls[1]["namespace"] == "alice"


def test_list_remote_unauthenticated_without_namespace_is_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.list_remote(registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION
    assert "fabricgate login" in str(exc_info.value)


def test_list_remote_ambiguous_scopes_requires_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.models.cli import Credentials

    monkeypatch.setattr(
        sdk_api.auth,
        "load_credentials",
        lambda _reg: Credentials(
            registry="http://test",
            token="tok",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            scopes=["ns:alice:read", "ns:bob:read"],
        ),
    )

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.list_remote(registry="http://test")
    assert exc_info.value.code == ExitKind.GENERIC


def test_list_remote_invalid_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.list_remote(namespace="Not Valid!", registry="http://test")
    assert exc_info.value.code == ExitKind.INVALID


def test_list_remote_registry_error_maps_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _Forbidden(_ListRemoteFakeClient):
        def search_designs(self, **kwargs: Any) -> SearchResponse:
            raise RegistryError(403, ErrorResponse(error=ErrorDetail(code="FORBIDDEN", message="forbidden")))

    _patch_all_rc(monkeypatch, _Forbidden)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.list_remote(namespace="private", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


# ===========================================================================
# _helpers.py internal unit tests
# ===========================================================================


def test_parse_design_ref_invalid_format() -> None:
    from fabricgate.sdk._helpers import _parse_design_ref

    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        _parse_design_ref("no-colon-here")


def test_parse_design_ref_optional_empty_version() -> None:
    from fabricgate.sdk._helpers import _parse_design_ref_optional_version

    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        _parse_design_ref_optional_version("ns/design:")


def test_parse_design_ref_optional_no_slash() -> None:
    from fabricgate.sdk._helpers import _parse_design_ref_optional_version

    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        _parse_design_ref_optional_version("nonamespace")


def test_validate_design_name_invalid() -> None:
    from fabricgate.sdk._helpers import _validate_design_name

    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        _validate_design_name("123-bad!", "design", "123-bad!/design")


def test_validate_semver_invalid() -> None:
    from fabricgate.sdk._helpers import _validate_semver

    with pytest.raises(sdk_api.SDKError, match="Invalid version"):
        _validate_semver("1.0")


def test_validate_stats_date_range_invalid_from_date() -> None:
    from fabricgate.sdk._helpers import _validate_stats_date_range

    with pytest.raises(sdk_api.SDKError, match="Invalid from_date"):
        _validate_stats_date_range("not-a-date", None)


def test_validate_stats_date_range_reversed() -> None:
    from fabricgate.sdk._helpers import _validate_stats_date_range

    with pytest.raises(sdk_api.SDKError, match="from_date must be"):
        _validate_stats_date_range("2026-01-31", "2026-01-01")


def test_find_manifest_path_not_found(tmp_path: Path) -> None:
    from fabricgate.sdk._helpers import _find_manifest_path

    with pytest.raises(sdk_api.SDKError, match="Manifest not found"):
        _find_manifest_path(tmp_path)


def test_extract_artifact_refs_no_artifacts() -> None:
    from unittest.mock import MagicMock

    from fabricgate.sdk._helpers import _extract_artifact_refs

    manifest = MagicMock()
    manifest.artifacts = None
    assert _extract_artifact_refs(manifest) == []


def test_registry_exit_code_dependency_unresolvable() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(
        409,
        ErrorResponse(error=ErrorDetail(code="DEPENDENCY_UNRESOLVABLE", message="unresolvable")),
    )
    assert _registry_error_kind(exc) == ExitKind.UNRESOLVABLE


def test_registry_exit_code_shell_not_found() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(
        409,
        ErrorResponse(error=ErrorDetail(code="SHELL_NOT_FOUND", message="shell not found")),
    )
    assert _registry_error_kind(exc) == ExitKind.SHELL_NOT_FOUND


def test_default_namespace_from_scopes_multiple_namespaces() -> None:
    from fabricgate.sdk._helpers import _default_namespace_from_scopes

    result = _default_namespace_from_scopes(["ns:alice:read", "ns:bob:write"])
    assert result is None


def test_quota_warning_message_designs_at_limit() -> None:
    from fabricgate.sdk._helpers import _quota_warning_message

    response = QuotaResponse.model_validate(
        {
            "namespace": "alice",
            "storage": {"used_bytes": 0, "limit_bytes": 10_000_000_000, "used_percent": 0.0},
            "versions_per_design": {"limit": 100},
            "designs": {"used": 85, "limit": 100},
            "file_size_limit_bytes": 524_288_000,
        }
    )
    msg = _quota_warning_message(response)
    assert msg is not None


def test_normalize_base_version_wrong_design() -> None:
    from fabricgate.sdk._helpers import _normalize_base_version

    with pytest.raises(sdk_api.SDKError, match="Base ref must target"):
        _normalize_base_version("ns", "design", "other/design:1.0.0")


def test_verify_attestation_cosign_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_puller_mod.shutil, "which", lambda _: None)

    with pytest.raises(AttestationUnavailableError, match="cosign is not installed"):
        _puller_mod._verify_attestation(tmp_path, ["design.bit"])


def test_verify_attestation_cosign_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    monkeypatch.setattr(_puller_mod.shutil, "which", lambda _: "/usr/bin/cosign")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "verification failed"
    monkeypatch.setattr(_puller_mod.subprocess, "run", lambda *_a, **_kw: mock_result)

    artifact = tmp_path / "design.bit"
    artifact.write_bytes(b"fake")
    with pytest.raises(AttestationError, match="Attestation verification failed"):
        _puller_mod._verify_attestation(tmp_path, ["design.bit"])


# ===========================================================================
# designs.py additional coverage tests
# ===========================================================================


def test_yank_exit_code_404() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))
    assert _registry_error_kind(exc) == ExitKind.NOT_FOUND


def test_deprecate_exit_code_404() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))
    assert _registry_error_kind(exc) == ExitKind.NOT_FOUND


def test_license_check_exit_code_404() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))
    assert _registry_error_kind(exc) == ExitKind.NOT_FOUND


def test_info_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrorClient(_FakeRegistryClient):
        def get_version(self, *_a, **_kw):
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))

    _patch_all_rc(monkeypatch, _ErrorClient)
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.info("test-ns/blink:1.0.0")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def _write_push_project_custom_board(root: Path) -> None:
    import hashlib as _hashlib

    platform_dir = root / "custom-xczu7ev" / "pynq"
    platform_dir.mkdir(parents=True)

    bitstream = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    hwh = b"<hwh/>"
    (platform_dir / "design.bit").write_bytes(bitstream)
    (platform_dir / "design.hwh").write_bytes(hwh)

    manifest_lines = [
        "schema: fabricgate-platform/v1",
        "runtime: pynq",
        "board: custom-xczu7ev",
        "design_ref: test-ns/blink:1.0.0",
        "artifacts:",
        "  bitstream:",
        "    file: design.bit",
        f"    sha256: {_hashlib.sha256(bitstream).hexdigest()}",
        "  hwh:",
        "    file: design.hwh",
        f"    sha256: {_hashlib.sha256(hwh).hexdigest()}",
    ]
    manifest_yaml = chr(10).join(manifest_lines)
    (platform_dir / "manifest.yaml").write_text(manifest_yaml)

    digest = f"sha256:{_hashlib.sha256(manifest_yaml.encode()).hexdigest()}"
    index_lines = [
        "schema: fabricgate-index/v1",
        "name: test-ns/blink",
        "version: 1.0.0",
        "platforms:",
        "  - platform: custom-xczu7ev/pynq",
        f"    digest: {digest}",
    ]
    (root / "fabricgate-index.yaml").write_text(chr(10).join(index_lines))


def test_push_board_override_replaces_custom_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project_custom_board(tmp_path)
    captured: dict[str, str] = {}

    def _fake_collect_artifacts(_project_dir, index, **_kwargs):
        captured["platform"] = str(index.platforms[0].platform)
        return {"index": b"ok"}

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)
    monkeypatch.setattr(_sdk_designs_push_mod, "collect_artifacts", _fake_collect_artifacts)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    result = sdk_api.push(tmp_path, token="tok", board_override="generic-xczu7ev", registry="http://test")
    assert result.name == "test-ns/blink"
    assert captured["platform"] == "generic-xczu7ev/pynq"


def test_push_registry_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrorClient(_FakePushRegistryClient):
        def publish_version(self, *_a, **_kw):
            raise RegistryError(409, ErrorResponse(error=ErrorDetail(code="CONFLICT", message="exists")))

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _ErrorClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.push(tmp_path, token="tok", registry="http://test")
    assert exc_info.value.code == ExitKind.INVALID


def test_pull_deprecated_with_successor_and_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:

    class _DeprecatedDetailClient(_FakeRegistryClientWithDeps):
        def get_version(self, namespace, design, version):
            resp = super().get_version(namespace, design, version)
            return resp.model_copy(
                update={
                    "deprecated": True,
                    "deprecation_message": "Use v2.0.0 instead.",
                    "successor": "test-ns/blink:2.0.0",
                }
            )

    _patch_all_rc(monkeypatch, _DeprecatedDetailClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    result = sdk_api.pull(
        "test-ns/blink:1.0.0",
        output=tmp_path,
        platform="xc7z020/pynq",
        registry="http://test",
    )
    assert result.deprecated_warning is not None


def test_pull_verify_attestation_cosign_not_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)
    monkeypatch.setattr(_puller_mod.shutil, "which", lambda _: None)

    with pytest.raises(sdk_api.SDKError, match="cosign is not installed"):
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            output=tmp_path,
            platform="xc7z020/pynq",
            verify_attestation=True,
            registry="http://test",
        )


def test_verify_invalid_artifact_path(tmp_path: Path) -> None:
    manifest_lines = [
        "schema: fabricgate-platform/v1",
        "runtime: pynq",
        "board: pynq-z2",
        "design_ref: test-ns/blink:1.0.0",
        "artifacts:",
        "  bitstream:",
        "    file: ../../../etc/passwd",
        "    sha256: " + "a" * 64,
        "  hwh:",
        "    file: design.hwh",
        "    sha256: " + "b" * 64,
    ]
    (tmp_path / "manifest.yaml").write_text(chr(10).join(manifest_lines))

    with pytest.raises(sdk_api.SDKError, match="Invalid artifact filename"):
        sdk_api.verify(str(tmp_path))


def test_verify_artifact_not_found(tmp_path: Path) -> None:
    manifest_lines = [
        "schema: fabricgate-platform/v1",
        "runtime: pynq",
        "board: pynq-z2",
        "design_ref: test-ns/blink:1.0.0",
        "artifacts:",
        "  bitstream:",
        "    file: missing.bit",
        "    sha256: " + "a" * 64,
        "  hwh:",
        "    file: design.hwh",
        "    sha256: " + "b" * 64,
    ]
    (tmp_path / "manifest.yaml").write_text(chr(10).join(manifest_lines))

    with pytest.raises(sdk_api.SDKError, match="Artifact not found"):
        sdk_api.verify(str(tmp_path))


def test_quota_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_QuotaFakeClient):
        def get_namespace_quota(self, _ns):
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))

    _patch_all_rc(monkeypatch, _NotFoundClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.quota(namespace="ghost", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_stats_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_StatsFakeClient):
        def get_design_stats(self, *_a, **_kw):
            raise NetworkError("Network error: connection refused")

    _patch_all_rc(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.stats(design_ref="alice/blink", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_yank_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkClient(_YankFakeClient):
        def yank_version(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _NetworkClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.yank("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_deprecate_empty_message_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())

    with pytest.raises(sdk_api.SDKError, match="--message is required"):
        sdk_api.deprecate("alice/counter:1.0.0", message="   ", registry="http://test")


def test_undeprecate_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError, match="Not authenticated") as exc_info:
        sdk_api.undeprecate("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.PERMISSION


def test_undeprecate_multi_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _YankFakeClient)

    results = sdk_api.undeprecate("alice/counter", versions=["1.0.0", "1.1.0"], registry="http://test")
    assert len(results) == 2
    assert all(not r.deprecated for r in results)


def test_diff_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrorClient(_FakeRegistryClient):
        def get_version_diff(self, *_a, **_kw):
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))

    _patch_all_rc(monkeypatch, _ErrorClient)
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.diff("test-ns/blink:1.0.0", base="0.9.0", registry="http://test")
    assert exc_info.value.code == ExitKind.NOT_FOUND


def test_license_check_no_check_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.models.api.responses import LicenseCheckResponse

    class _NoCheckClient(_FakeRegistryClient):
        def license_check(self, *_a, **_kw):
            return LicenseCheckResponse.model_validate(
                {
                    "design": "test-ns/blink",
                    "version": "1.0.0",
                    "tool_requirements": [],
                    "check": None,
                    "disclaimer": "check manually",
                }
            )

    _patch_all_rc(monkeypatch, _NoCheckClient)
    result = sdk_api.license_check("test-ns/blink:1.0.0", registry="http://test")
    assert result.check is None


def test_license_check_with_check_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.models.api.responses import LicenseCheckResponse

    class _WithCheckClient(_FakeRegistryClient):
        def license_check(self, *_a, **_kw):
            return LicenseCheckResponse.model_validate(
                {
                    "design": "test-ns/blink",
                    "version": "1.0.0",
                    "tool_requirements": [
                        {"tool": "vivado", "min_version": "2022.1", "edition": "standard", "required": True}
                    ],
                    "check": {
                        "tool": "vivado",
                        "edition": "standard",
                        "meets_requirements": True,
                        "notes": ["version OK"],
                    },
                    "disclaimer": "none",
                }
            )

    _patch_all_rc(monkeypatch, _WithCheckClient)
    result = sdk_api.license_check("test-ns/blink:1.0.0", registry="http://test")
    assert result.check is not None
    assert result.check.meets_requirements is True


def test_parse_semver_tuple_invalid() -> None:
    from fabricgate.sdk.designs.watch import _parse_semver_tuple

    with pytest.raises(sdk_api.SDKError, match="Invalid semver string"):
        _parse_semver_tuple("1.0")


def test_parse_design_ref_optional_invalid_semver() -> None:
    from fabricgate.sdk._helpers import _parse_design_ref_optional_version

    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        _parse_design_ref_optional_version("alice/blink:1.0")


def test_validate_stats_date_range_invalid_to_date() -> None:
    from fabricgate.sdk._helpers import _validate_stats_date_range

    with pytest.raises(sdk_api.SDKError, match="Invalid to_date"):
        _validate_stats_date_range("2026-01-01", "invalid")


def test_sum_recent_empty_series() -> None:
    from fabricgate.sdk._helpers import _sum_recent

    assert _sum_recent([], 7) == 0


def test_extract_artifact_refs_list_branch() -> None:
    from fabricgate.sdk._helpers import _extract_artifact_refs

    class _ListItem:
        file = "a.bit"
        sha256 = "a" * 64

    class _Artifacts:
        model_fields: ClassVar[dict[str, None]] = {"extra": None}

        def __init__(self) -> None:
            self.extra = [_ListItem()]

    class _Manifest:
        def __init__(self) -> None:
            self.artifacts = _Artifacts()

    manifest = _Manifest()
    refs = _extract_artifact_refs(manifest)
    assert len(refs) == 1


def test_quota_warning_message_none() -> None:
    from fabricgate.sdk._helpers import _quota_warning_message

    response = QuotaResponse.model_validate(
        {
            "namespace": "alice",
            "storage": {"used_bytes": 0, "limit_bytes": 10_000_000_000, "used_percent": 1.0},
            "versions_per_design": {"limit": 100},
            "designs": {"used": 10, "limit": 100},
            "file_size_limit_bytes": 524_288_000,
        }
    )
    assert _quota_warning_message(response) is None


def test_resolve_and_download_deps_404_returns_empty(tmp_path: Path) -> None:
    from fabricgate.client.puller import _resolve_and_download_deps
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _Client:
        def get_dependencies(self, *_a, **_kw):
            raise RegistryError(404, ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="not found")))

    result = _resolve_and_download_deps(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)
    assert result == []


def test_resolve_and_download_deps_reraises_unhandled_registry_error(tmp_path: Path) -> None:
    from fabricgate.client.puller import _resolve_and_download_deps
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _Client:
        def get_dependencies(self, *_a, **_kw):
            raise RegistryError(500, ErrorResponse(error=ErrorDetail(code="SERVER", message="down")))

    with pytest.raises(RegistryError):
        _resolve_and_download_deps(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)


def test_resolve_and_download_deps_invalid_artifact_path(tmp_path: Path) -> None:
    from fabricgate.client.puller import _resolve_and_download_deps
    from fabricgate.models.api.responses import DependenciesResponse

    class _Client:
        def get_dependencies(self, *_a, **_kw):
            return DependenciesResponse.model_validate(
                {
                    "root": "a/b:1.0.0",
                    "platform": "xc7z020/pynq",
                    "dependencies": [
                        {
                            "name": "dep-ns/dep-design",
                            "resolved_version": "0.1.0",
                            "platform": "xc7z020/pynq",
                            "optional": False,
                            "depth": 1,
                            "required_by": "test-ns/blink",
                        }
                    ],
                }
            )

        def get_platform_manifest_bytes(self, *_a, **_kw):
            return "\n".join(
                [
                    "schema: fabricgate-platform/v1",
                    "runtime: pynq",
                    "board: pynq-z2",
                    "design_ref: dep-ns/dep-design:0.1.0",
                    "artifacts:",
                    "  bitstream:",
                    "    file: ../bad.bit",
                    "    sha256: " + "a" * 64,
                    "  hwh:",
                    "    file: design.hwh",
                    "    sha256: " + "b" * 64,
                ]
            ).encode("utf-8")

        def download_artifact(self, *_a, **_kw):
            return b"x"

    with pytest.raises(IntegrityError, match="Invalid artifact filename in dependency manifest"):
        _resolve_and_download_deps(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)


def test_resolve_and_download_deps_digest_mismatch(tmp_path: Path) -> None:
    from fabricgate.client.puller import _resolve_and_download_deps
    from fabricgate.models.api.responses import DependenciesResponse

    class _Client:
        def get_dependencies(self, *_a, **_kw):
            return DependenciesResponse.model_validate(
                {
                    "root": "a/b:1.0.0",
                    "platform": "xc7z020/pynq",
                    "dependencies": [
                        {
                            "name": "dep-ns/dep-design",
                            "resolved_version": "0.1.0",
                            "platform": "xc7z020/pynq",
                            "optional": False,
                            "depth": 1,
                            "required_by": "test-ns/blink",
                        }
                    ],
                }
            )

        def get_platform_manifest_bytes(self, *_a, **_kw):
            return "\n".join(
                [
                    "schema: fabricgate-platform/v1",
                    "runtime: pynq",
                    "board: pynq-z2",
                    "design_ref: dep-ns/dep-design:0.1.0",
                    "artifacts:",
                    "  bitstream:",
                    "    file: design.bit",
                    "    sha256: " + "a" * 64,
                    "  hwh:",
                    "    file: design.hwh",
                    "    sha256: " + "b" * 64,
                ]
            ).encode("utf-8")

        def download_artifact(self, *_a, **_kw):
            return b"wrong"

    with pytest.raises(IntegrityError, match="Digest mismatch for dependency artifact"):
        _resolve_and_download_deps(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)


def test_maybe_download_shell_invalid_artifact_path(tmp_path: Path) -> None:
    from fabricgate.client.puller import _maybe_download_shell
    from fabricgate.models.api.responses import ShellInfo, ShellResponse

    class _Client:
        def get_shell(self, *_a, **_kw):
            return ShellResponse(
                shell=ShellInfo(
                    name="shell-ns/shell-design",
                    version="1.0.0",
                    board="zcu104",
                    runtime="pynq",
                    bitstream_type="full",
                    artifacts=[],
                    pull_url="https://example.com",
                )
            )

        def get_platform_manifest_bytes(self, *_a, **_kw):
            return "\n".join(
                [
                    "schema: fabricgate-platform/v1",
                    "runtime: pynq",
                    "board: zcu104",
                    "design_ref: shell-ns/shell-design:1.0.0",
                    "artifacts:",
                    "  bitstream:",
                    "    file: ../bad.bit",
                    "    sha256: " + "a" * 64,
                    "  hwh:",
                    "    file: design.hwh",
                    "    sha256: " + "b" * 64,
                ]
            ).encode("utf-8")

        def download_artifact(self, *_a, **_kw):
            return b"x"

    with pytest.raises(IntegrityError, match="Invalid artifact filename in shell manifest"):
        _maybe_download_shell(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)


def test_maybe_download_shell_ignores_not_a_partial(tmp_path: Path) -> None:
    from fabricgate.client.puller import _maybe_download_shell
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _Client:
        def get_shell(self, *_a, **_kw):
            error = ErrorResponse(
                error=ErrorDetail(
                    code="NOT_A_PARTIAL",
                    message="Platform zcu104/pynq has bitstream_type 'None', not 'partial'",
                )
            )
            raise RegistryError(422, error)

    assert _maybe_download_shell(_Client(), "a", "b", "1.0.0", "zcu104", "pynq", tmp_path, True) is None


def test_maybe_download_shell_digest_mismatch(tmp_path: Path) -> None:
    from fabricgate.client.puller import _maybe_download_shell
    from fabricgate.models.api.responses import ShellInfo, ShellResponse

    class _Client:
        def get_shell(self, *_a, **_kw):
            return ShellResponse(
                shell=ShellInfo(
                    name="shell-ns/shell-design",
                    version="1.0.0",
                    board="zcu104",
                    runtime="pynq",
                    bitstream_type="full",
                    artifacts=[],
                    pull_url="https://example.com",
                )
            )

        def get_platform_manifest_bytes(self, *_a, **_kw):
            return "\n".join(
                [
                    "schema: fabricgate-platform/v1",
                    "runtime: pynq",
                    "board: zcu104",
                    "design_ref: shell-ns/shell-design:1.0.0",
                    "artifacts:",
                    "  bitstream:",
                    "    file: shell.bit",
                    "    sha256: " + "a" * 64,
                    "  hwh:",
                    "    file: shell.hwh",
                    "    sha256: " + "b" * 64,
                ]
            ).encode("utf-8")

        def download_artifact(self, *_a, **_kw):
            return b"wrong"

    with pytest.raises(IntegrityError, match="Digest mismatch for shell artifact"):
        _maybe_download_shell(_Client(), "a", "b", "1.0.0", "xc7z020", "pynq", tmp_path, True)


def test_yank_deprecate_license_exit_code_server_error() -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
    from fabricgate.sdk._helpers import _registry_error_kind

    exc = RegistryError(500, ErrorResponse(error=ErrorDetail(code="E", message="m")))
    assert _registry_error_kind(exc) == ExitKind.INFRA
    assert _registry_error_kind(exc) == ExitKind.INFRA
    assert _registry_error_kind(exc) == ExitKind.INFRA


def test_search_registry_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _ErrorClient(_FakeRegistryClient):
        def search_designs(self, *_a, **_kw):
            raise RegistryError(500, ErrorResponse(error=ErrorDetail(code="E", message="m")))

    _patch_all_rc(monkeypatch, _ErrorClient)
    with pytest.raises(sdk_api.SDKError):
        sdk_api.search("blink", registry="http://test")


def test_push_publish_error_from_index_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fabricgate.client.publisher import PublishError

    monkeypatch.setattr(
        _sdk_designs_push_mod,
        "load_design_index",
        lambda *_a, **_kw: (_ for _ in ()).throw(PublishError("bad")),
    )
    with pytest.raises(sdk_api.SDKError, match="bad"):
        sdk_api.push(tmp_path, token="tok", registry="http://test")


def test_push_validation_error_from_index_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ValidationError(Exception):
        pass

    monkeypatch.setattr(
        _sdk_designs_push_mod,
        "load_design_index",
        lambda *_a, **_kw: (_ for _ in ()).throw(ValidationError("invalid index")),
    )
    with pytest.raises(sdk_api.SDKError, match="Invalid design index"):
        sdk_api.push(tmp_path, token="tok", registry="http://test")


def test_push_reraises_unexpected_index_load_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        _sdk_designs_push_mod,
        "load_design_index",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    with pytest.raises(RuntimeError, match="unexpected"):
        sdk_api.push(tmp_path, token="tok", registry="http://test")


def test_push_invalid_design_name_in_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Index:
        name = "invalidname"
        version = "1.0.0"
        platforms: ClassVar[list] = []

    monkeypatch.setattr(
        _sdk_designs_push_mod,
        "load_design_index",
        lambda *_a, **_kw: (_Index(), tmp_path / "fabricgate-index.yaml"),
    )
    with pytest.raises(sdk_api.SDKError, match="Invalid design name in index"):
        sdk_api.push(tmp_path, token="tok", registry="http://test")


def test_push_quota_error_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _QuotaErrorClient(_FakePushRegistryClient):
        def get_namespace_quota(self, _ns):
            raise RegistryError(500, ErrorResponse(error=ErrorDetail(code="E", message="m")))

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _QuotaErrorClient)
    result = sdk_api.push(tmp_path, token="tok", registry="http://test")
    assert result.quota_warning is None


def test_pull_resolution_error_exit_code_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fabricgate.client.resolver import ResolutionError

    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)
    monkeypatch.setattr(
        _puller_mod,
        "resolve_platform_detailed",
        lambda *_a, **_kw: (_ for _ in ()).throw(ResolutionError("no platform")),
    )
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            output=tmp_path,
            platform="xc7z020/pynq",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.UNRESOLVABLE


def test_pull_oserror_exit_code_4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_all_rc(monkeypatch, _FakeRegistryClientWithDeps)
    monkeypatch.setattr(
        _puller_mod.cache,
        "store",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.pull(
            "test-ns/blink:1.0.0",
            output=tmp_path,
            platform="xc7z020/pynq",
            cache_dir=tmp_path / "cache",
            registry="http://test",
        )
    assert exc_info.value.code == ExitKind.INFRA


def test_pull_invalid_artifact_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _BadManifestClient(_FakeRegistryClientWithDeps):
        def __init__(self, *_args, **_kwargs) -> None:
            self.manifest_bytes = "\n".join(
                [
                    "schema: fabricgate-platform/v1",
                    "runtime: pynq",
                    "board: pynq-z2",
                    "design_ref: test-ns/blink:1.0.0",
                    "artifacts:",
                    "  bitstream:",
                    "    file: ../bad.bit",
                    "    sha256: " + "a" * 64,
                    "  hwh:",
                    "    file: design.hwh",
                    "    sha256: " + "b" * 64,
                ]
            ).encode("utf-8")

    _patch_all_rc(monkeypatch, _BadManifestClient)
    with pytest.raises(sdk_api.SDKError, match="Invalid artifact filename in manifest"):
        sdk_api.pull("test-ns/blink:1.0.0", output=tmp_path, platform="xc7z020/pynq", registry="http://test")


def test_pull_digest_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _MismatchClient(_FakeRegistryClientWithDeps):
        def download_artifact(self, *_a, **_kw):
            return b"mismatch"

    _patch_all_rc(monkeypatch, _MismatchClient)
    with pytest.raises(sdk_api.SDKError, match="Digest mismatch"):
        sdk_api.pull("test-ns/blink:1.0.0", output=tmp_path, platform="xc7z020/pynq", registry="http://test")


def test_stats_invalid_period() -> None:
    with pytest.raises(sdk_api.SDKError, match="Invalid period"):
        sdk_api.stats(design_ref="alice/blink", period="yearly", registry="http://test")  # type: ignore[arg-type]


def test_yank_invalid_design_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        sdk_api.yank("noslash", registry="http://test")


def test_deprecate_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)
    with pytest.raises(sdk_api.SDKError, match="Not authenticated"):
        sdk_api.deprecate("alice/counter:1.0.0", message="msg", registry="http://test")


def test_deprecate_invalid_ref_no_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        sdk_api.deprecate("noslash", versions=["1.0.0"], message="msg", registry="http://test")


def test_deprecate_no_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    with pytest.raises(sdk_api.SDKError, match="No versions specified"):
        sdk_api.deprecate("alice/counter", message="msg", registry="http://test")


def test_deprecate_too_many_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    versions = [f"1.{i}.0" for i in range(51)]
    with pytest.raises(sdk_api.SDKError, match="Maximum 50"):
        sdk_api.deprecate("alice/counter", versions=versions, message="msg", registry="http://test")


def test_deprecate_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkClient(_YankFakeClient):
        def deprecate_version(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _NetworkClient)
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.deprecate("alice/counter:1.0.0", message="msg", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_undeprecate_invalid_ref_no_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    with pytest.raises(sdk_api.SDKError, match="Invalid design ref"):
        sdk_api.undeprecate("noslash", registry="http://test")


def test_undeprecate_no_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    with pytest.raises(sdk_api.SDKError, match="No versions specified"):
        sdk_api.undeprecate("alice/counter", registry="http://test")


def test_undeprecate_too_many_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    versions = [f"1.{i}.0" for i in range(51)]
    with pytest.raises(sdk_api.SDKError, match="Maximum 50"):
        sdk_api.undeprecate("alice/counter", versions=versions, registry="http://test")


def test_undeprecate_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkClient(_YankFakeClient):
        def undeprecate_version(self, *_a, **_kw):
            raise NetworkError("Network error: timeout")

    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: _yank_creds())
    _patch_all_rc(monkeypatch, _NetworkClient)
    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.undeprecate("alice/counter:1.0.0", registry="http://test")
    assert exc_info.value.code == ExitKind.INFRA


def test_push_artifact_url_sends_url_part_and_requests_no_ticket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--artifact-url: the URL travels as a text part; no ticket, no upload for that file."""
    url = "https://github.com/acme/blink/releases/download/v1/design.bit"
    captured: dict[str, object] = {}

    class _RecordingClient(_FakePushRegistryClient):
        def publish_version(self, namespace, design, version, files):
            captured["files"] = dict(files)
            captured["client"] = self
            return super().publish_version(namespace, design, version, files)

    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _RecordingClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    sdk_api.push(tmp_path, token="tok", artifact_urls={"design.bit": url})

    files = captured["files"]
    assert files["platform:xc7z020/pynq:artifact-url:design.bit"] == url.encode()
    assert not [key for key in files if ":artifact:" in key]
    client = captured["client"]
    assert [item["filename"] for item in client.upload_requests[0]] == ["design.hwh"]
    assert [name for name, _sha, _size in client.uploaded] == ["design.hwh"]


def test_push_artifact_url_invalid_maps_to_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_push_project(tmp_path)
    _patch_all_rc(monkeypatch, _FakePushRegistryClient)
    monkeypatch.setattr(sdk_api.auth, "load_credentials", lambda _reg: None)

    with pytest.raises(sdk_api.SDKError) as excinfo:
        sdk_api.push(tmp_path, token="tok", artifact_urls={"design.bit": "http://example.com/design.bit"})
    assert excinfo.value.code == ExitKind.INVALID


def test_top_level_sdk_exports_list_remote() -> None:
    from fabricgate import sdk

    assert sdk.list_remote is _sdk_designs_mod.list_remote
    assert "list_remote" in sdk.__all__
