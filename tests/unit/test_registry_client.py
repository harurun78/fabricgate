"""Tests for RegistryClient — HTTP client for the registry API."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from fabricgate.client.registry_client import NetworkError, RegistryClient, RegistryError

_NOW = datetime.now(tz=UTC).isoformat()


def _transport(
    status: int = 200,
    body: dict | list | bytes = b"",
    content_type: str = "application/json",
) -> httpx.MockTransport:
    """Create a mock transport returning a fixed response."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, (dict, list)):
            return httpx.Response(
                status,
                json=body,
                request=request,
                headers={"content-type": content_type},
            )
        return httpx.Response(
            status,
            content=body,
            request=request,
            headers={"content-type": content_type},
        )

    return httpx.MockTransport(_handler)


def _make_client(transport: httpx.MockTransport, token: str | None = None) -> RegistryClient:
    """Build a RegistryClient with a mock transport injected."""
    client = RegistryClient(base_url="http://test/api/v1", token=token)
    client._client = httpx.Client(
        base_url="http://test/api/v1",
        transport=transport,
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    return client


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestClientContextManager:
    def test_enter_exit(self) -> None:
        body = {"designs": [], "total": 0, "page": 1, "per_page": 20}
        with _make_client(_transport(200, body)) as client:
            resp = client.search_designs()
            assert resp.total == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_raises_registry_error_on_400(self) -> None:
        err_body = {
            "error": {"code": "VALIDATION_ERROR", "message": "bad request"},
        }
        transport = _transport(400, err_body)
        client = _make_client(transport)

        with pytest.raises(RegistryError) as exc_info:
            client.search_designs()
        assert exc_info.value.status_code == 400
        assert "VALIDATION_ERROR" in str(exc_info.value)

    def test_raises_network_error_on_unparseable_error(self) -> None:
        """A 4xx/5xx whose body is not a valid ErrorResponse surfaces as NetworkError
        (via raise_for_status), so httpx never escapes the client layer; the SDK
        still maps NetworkError to ExitKind.INFRA."""
        transport = _transport(500, b"internal error", content_type="text/plain")
        client = _make_client(transport)

        with pytest.raises(NetworkError):
            client.search_designs()

    def test_raises_network_error_on_transport_error(self) -> None:
        """A transport-layer failure (connect/DNS/timeout) is translated into
        NetworkError inside _request, keeping httpx confined to this layer."""

        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _make_client(httpx.MockTransport(_handler))

        with pytest.raises(NetworkError) as exc_info:
            client.search_designs()
        assert "Network error" in str(exc_info.value)
        assert exc_info.value.status_code == 0
        assert exc_info.value.error is None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestSearchDesigns:
    def test_returns_search_response(self) -> None:
        body = {"designs": [], "total": 0, "page": 1, "per_page": 20}
        client = _make_client(_transport(200, body))

        result = client.search_designs(q="test", page=1)

        assert result.total == 0
        assert result.designs == []


class TestGetDesign:
    def test_returns_design_detail(self) -> None:
        body = {
            "name": "demo/blink",
            "summary": "LED blink",
            "versions": [],
            "tags": [],
            "created_at": _NOW,
        }
        client = _make_client(_transport(200, body))

        result = client.get_design("demo", "blink")

        assert result.name == "demo/blink"


class TestGetVersion:
    def test_returns_version_detail(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.0.0",
            "platforms": [],
            "published_at": _NOW,
            "yanked": False,
        }
        client = _make_client(_transport(200, body))

        result = client.get_version("demo", "blink", "1.0.0")

        assert result.version == "1.0.0"


class TestGetPlatformManifestBytes:
    def test_returns_raw_bytes(self) -> None:
        raw = b"manifest-content"
        client = _make_client(_transport(200, raw, content_type="application/octet-stream"))

        result = client.get_platform_manifest_bytes("demo", "blink", "1.0.0", "esp32", "espidf")

        assert result == raw


class TestDownloadArtifact:
    def test_returns_artifact_bytes(self) -> None:
        raw = b"artifact-binary"
        client = _make_client(_transport(200, raw, content_type="application/octet-stream"))

        result = client.download_artifact(
            "demo",
            "blink",
            "1.0.0",
            "esp32",
            "espidf",
            "main.bin",
        )

        assert result == raw


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestDeviceAuthorization:
    def test_returns_dict(self) -> None:
        body = {"device_code": "abc", "user_code": "1234", "interval": 5}
        client = _make_client(_transport(200, body))

        result = client.device_authorization()

        assert result["device_code"] == "abc"


class TestTokenExchange:
    def test_returns_login_response(self) -> None:
        body = {"token": "tok123", "expires_at": _NOW, "scopes": ["publish"]}
        client = _make_client(_transport(200, body))

        result = client.token_exchange(grant_type="device_code", device_code="abc")

        assert result.token == "tok123"


# ---------------------------------------------------------------------------
# Publish / Yank
# ---------------------------------------------------------------------------


class TestArtifactUploads:
    """Presigned direct upload path."""

    def test_create_artifact_uploads_returns_tickets(self) -> None:
        body = {
            "uploads": [
                {
                    "filename": "design.bit",
                    "sha256": "a" * 64,
                    "url": "https://storage.example.com/put",
                    "headers": {"x-amz-checksum-sha256": "b64"},
                    "expires_in": 900,
                }
            ]
        }
        client = _make_client(_transport(200, body))

        result = client.create_artifact_uploads(
            "demo", "blink", [{"filename": "design.bit", "sha256": "a" * 64, "size": 4}]
        )

        assert result.uploads[0].url == "https://storage.example.com/put"
        assert result.uploads[0].headers == {"x-amz-checksum-sha256": "b64"}

    def test_upload_artifact_sends_the_signed_checksum_header(self, monkeypatch) -> None:
        from fabricgate.models.api.responses import ArtifactUploadTicket

        seen: dict[str, object] = {}

        def _fake_put(url: str, **kwargs: object) -> httpx.Response:
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            seen["content"] = kwargs.get("content")
            return httpx.Response(200, request=httpx.Request("PUT", url))

        monkeypatch.setattr(httpx, "put", _fake_put)
        ticket = ArtifactUploadTicket(
            filename="design.bit",
            sha256="a" * 64,
            url="https://storage.example.com/put",
            headers={"x-amz-checksum-sha256": "b64"},
        )

        _make_client(_transport(200, {})).upload_artifact(ticket, b"data")

        assert seen["url"] == "https://storage.example.com/put"
        assert seen["headers"] == {"x-amz-checksum-sha256": "b64"}
        assert seen["content"] == b"data"

    def test_upload_artifact_skips_when_no_url(self, monkeypatch) -> None:
        from fabricgate.models.api.responses import ArtifactUploadTicket

        def _fail(*_args: object, **_kwargs: object) -> httpx.Response:
            raise AssertionError("must not PUT when the object is already stored")

        monkeypatch.setattr(httpx, "put", _fail)
        ticket = ArtifactUploadTicket(filename="design.bit", sha256="a" * 64)

        _make_client(_transport(200, {})).upload_artifact(ticket, b"data")

    def test_upload_artifact_raises_on_digest_rejection(self, monkeypatch) -> None:
        """Storage answers 400 BadDigest when the bytes do not match the signature."""
        from fabricgate.models.api.responses import ArtifactUploadTicket

        def _bad_digest(url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                400,
                content=b"<Error><Code>BadDigest</Code></Error>",
                request=httpx.Request("PUT", url),
            )

        monkeypatch.setattr(httpx, "put", _bad_digest)
        ticket = ArtifactUploadTicket(
            filename="design.bit",
            sha256="a" * 64,
            url="https://storage.example.com/put",
            headers={"x-amz-checksum-sha256": "b64"},
        )

        with pytest.raises(NetworkError, match="BadDigest"):
            _make_client(_transport(200, {})).upload_artifact(ticket, b"tampered")


class TestPublishVersion:
    def test_returns_publish_response(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.0.0",
            "platforms": [],
            "published_at": _NOW,
        }
        client = _make_client(_transport(200, body))

        result = client.publish_version(
            "demo",
            "blink",
            "1.0.0",
            {"design_index.yaml": b"index-data"},
        )

        assert result.version == "1.0.0"


class TestYankVersion:
    def test_returns_yank_response(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.0.0",
            "yanked": True,
            "yanked_reason": "broken",
        }
        client = _make_client(_transport(200, body))

        result = client.yank_version("demo", "blink", "1.0.0", reason="broken")

        assert result.yanked is True


class TestDeprecateVersion:
    def test_returns_deprecate_response(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.0.0",
            "deprecated": True,
            "deprecation_message": "Upgrade to 2.0.0",
            "successor": "demo/blink:2.0.0",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/namespaces/demo/designs/blink/versions/1.0.0/deprecate"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.deprecate_version(
            "demo",
            "blink",
            "1.0.0",
            message="Upgrade to 2.0.0",
            successor="demo/blink:2.0.0",
        )

        assert result.deprecated is True
        assert result.deprecation_message == "Upgrade to 2.0.0"


class TestUndeprecateVersion:
    def test_returns_undeprecate_response(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.0.0",
            "deprecated": False,
            "deprecation_message": None,
            "successor": None,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/v1/namespaces/demo/designs/blink/versions/1.0.0/deprecate"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.undeprecate_version("demo", "blink", "1.0.0")

        assert result.deprecated is False


# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------


class TestListNamespaces:
    def test_strict_mode_rejects_str_datetime(self) -> None:
        body = [{"name": "demo", "display_name": "Demo", "description": "", "status": "active", "created_at": _NOW}]

        transport = _transport(200, body)
        client = _make_client(transport)

        # list_namespaces uses model_validate (not model_validate_json);
        # strict mode prevents str→datetime coercion — verify it raises.
        with pytest.raises(ValidationError):
            client.list_namespaces()


class TestGetNamespace:
    def test_returns_namespace(self) -> None:
        body = {
            "name": "demo",
            "display_name": "Demo",
            "description": "",
            "status": "active",
            "created_at": _NOW,
        }
        client = _make_client(_transport(200, body))

        result = client.get_namespace("demo")

        assert result.name == "demo"


# ---------------------------------------------------------------------------
# Dependencies (CLI-PULL-002)
# ---------------------------------------------------------------------------


class TestGetDependencies:
    def test_get_dependencies(self) -> None:
        """get_dependenciesの正常系。"""
        body = {
            "root": "demo/blink:1.0.0",
            "platform": "xc7z020/pynq",
            "dependencies": [
                {
                    "name": "dep-ns/dep-design",
                    "resolved_version": "0.1.0",
                    "platform": "xc7z020/pynq",
                    "optional": False,
                    "depth": 1,
                    "required_by": "demo/blink",
                }
            ],
        }
        client = _make_client(_transport(200, body))

        result = client.get_dependencies("demo", "blink", "1.0.0", "xc7z020", "pynq")

        assert result.root == "demo/blink:1.0.0"
        assert len(result.dependencies) == 1
        assert result.dependencies[0].name == "dep-ns/dep-design"
        assert result.dependencies[0].resolved_version == "0.1.0"
        assert result.dependencies[0].depth == 1


# ---------------------------------------------------------------------------
# Download Stats (CLI-STATS-001)
# ---------------------------------------------------------------------------


class TestGetDesignStats:
    def test_get_design_stats(self) -> None:
        body = {
            "name": "demo/blink",
            "total_downloads": 120,
            "period": "daily",
            "series": [
                {"date": "2026-03-25", "downloads": 12},
                {"date": "2026-03-26", "downloads": 18},
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/demo/designs/blink/stats"
            params = dict(request.url.params)
            assert params["period"] == "daily"
            assert params["from"] == "2026-03-01"
            assert params["to"] == "2026-03-31"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.get_design_stats(
            "demo",
            "blink",
            period="daily",
            from_date="2026-03-01",
            to_date="2026-03-31",
        )

        assert result.name == "demo/blink"
        assert result.total_downloads == 120
        assert len(result.series) == 2


class TestGetVersionStats:
    def test_get_version_stats(self) -> None:
        body = {
            "name": "demo/blink",
            "version": "1.2.0",
            "total_downloads": 48,
            "period": "weekly",
            "series": [
                {"date": "2026-03-01", "downloads": 20},
                {"date": "2026-03-08", "downloads": 28},
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/demo/designs/blink/versions/1.2.0/stats"
            params = dict(request.url.params)
            assert params["period"] == "weekly"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.get_version_stats("demo", "blink", "1.2.0", period="weekly")

        assert result.name == "demo/blink"
        assert result.version == "1.2.0"
        assert result.total_downloads == 48


class TestGetNamespaceStats:
    def test_get_namespace_stats(self) -> None:
        body = {
            "namespace": "demo",
            "total_downloads": 512,
            "top_designs": [
                {"name": "demo/blink", "total_downloads": 300},
                {"name": "demo/uart", "total_downloads": 212},
            ],
            "period_downloads": {"last_7d": 80, "last_30d": 220},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/demo/stats"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.get_namespace_stats("demo")

        assert result.namespace == "demo"
        assert result.total_downloads == 512
        assert result.period_downloads.last_7d == 80
        assert result.period_downloads.last_30d == 220


class TestGetNamespaceQuota:
    def test_get_namespace_quota(self) -> None:
        body = {
            "namespace": "demo",
            "storage": {"used_bytes": 1024, "limit_bytes": 10_240, "used_percent": 10.0},
            "versions_per_design": {"limit": 100},
            "designs": {"used": 3, "limit": 200},
            "file_size_limit_bytes": 524_288_000,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/demo/quota"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.get_namespace_quota("demo")

        assert result.namespace == "demo"
        assert result.storage.used_percent == 10.0
        assert result.designs.used == 3


# ---------------------------------------------------------------------------
# Shell (CLI-PULL-002)
# ---------------------------------------------------------------------------


class TestGetShell:
    def test_get_shell(self) -> None:
        """get_shellの正常系。"""
        body = {
            "shell": {
                "name": "shell-ns/shell-design",
                "version": "2.0.0",
                "board": "zcu104",
                "runtime": "pynq",
                "bitstream_type": "full",
                "artifacts": [
                    {"file": "shell.bit", "sha256": "a" * 64, "size": 1024},
                ],
                "pull_url": "https://example.com/pull/shell",
            }
        }
        client = _make_client(_transport(200, body))

        result = client.get_shell("demo", "blink", "1.0.0", "xc7z020", "pynq")

        assert result.shell.name == "shell-ns/shell-design"
        assert result.shell.version == "2.0.0"
        assert result.shell.board == "zcu104"
        assert len(result.shell.artifacts) == 1
        assert result.shell.artifacts[0].file == "shell.bit"


# ---------------------------------------------------------------------------
# API Keys (CLI-TOKEN-001)
# ---------------------------------------------------------------------------


class TestCreateApiKey:
    def test_create_api_key(self) -> None:
        """POST /users/me/api-keys の正常系。"""
        body = {
            "id": 42,
            "name": "ci-key",
            "key": "fgk_abc123secrettoken",
            "scopes": ["public:read"],
            "expires_at": _NOW,
            "created_at": _NOW,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/users/me/api-keys"
            import json as _json

            req_body = _json.loads(request.content)
            assert req_body["name"] == "ci-key"
            assert req_body["scopes"] == ["public:read"]
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.create_api_key("ci-key", ["public:read"], _NOW)

        assert result.id == 42
        assert result.name == "ci-key"
        assert result.key == "fgk_abc123secrettoken"
        assert result.scopes == ["public:read"]


class TestListApiKeys:
    def test_list_api_keys(self) -> None:
        """GET /users/me/api-keys の正常系。"""
        body = {
            "api_keys": [
                {
                    "id": 1,
                    "name": "key-alpha",
                    "scopes": ["public:read"],
                    "expires_at": _NOW,
                    "last_used_at": _NOW,
                    "created_at": _NOW,
                },
                {
                    "id": 2,
                    "name": "key-beta",
                    "scopes": ["public:read", "ns:alice:write"],
                    "expires_at": None,
                    "last_used_at": None,
                    "created_at": _NOW,
                },
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/users/me/api-keys"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.list_api_keys()

        assert len(result.api_keys) == 2
        assert result.api_keys[0].name == "key-alpha"
        assert result.api_keys[1].name == "key-beta"


class TestDeleteApiKey:
    def test_delete_api_key(self) -> None:
        """DELETE /users/me/api-keys/{id} の正常系。"""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/v1/users/me/api-keys/42"
            return httpx.Response(204, content=b"", request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        # Should not raise
        client.delete_api_key(42)


# ---------------------------------------------------------------------------
# Webhooks (CLI-WEBHOOK-001)
# ---------------------------------------------------------------------------


class TestCreateWebhook:
    def test_create_webhook(self) -> None:
        """POST /namespaces/{ns}/webhooks の正常系。"""
        body = {
            "id": 10,
            "url": "https://example.com/hook",
            "events": ["design.published", "design.yanked"],
            "design": None,
            "secret": "whsec_abcdef1234567890",
            "status": "active",
            "created_at": _NOW,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/namespaces/myns/webhooks"
            import json as _json

            req_body = _json.loads(request.content)
            assert req_body["url"] == "https://example.com/hook"
            assert req_body["events"] == ["design.published", "design.yanked"]
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.create_webhook("myns", "https://example.com/hook", ["design.published", "design.yanked"])

        assert result.id == 10
        assert result.url == "https://example.com/hook"
        assert result.events == ["design.published", "design.yanked"]
        assert result.secret == "whsec_abcdef1234567890"
        assert result.status == "active"


class TestListWebhooks:
    def test_list_webhooks(self) -> None:
        """GET /namespaces/{ns}/webhooks の正常系。"""
        body = {
            "webhooks": [
                {
                    "id": 10,
                    "url": "https://example.com/hook",
                    "events": ["design.published"],
                    "design": None,
                    "status": "active",
                    "last_delivered_at": _NOW,
                    "created_at": _NOW,
                },
                {
                    "id": 11,
                    "url": "https://example.com/hook2",
                    "events": ["design.published", "design.yanked"],
                    "design": "blink",
                    "status": "active",
                    "last_delivered_at": None,
                    "created_at": _NOW,
                },
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/myns/webhooks"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.list_webhooks("myns")

        assert len(result.webhooks) == 2
        assert result.webhooks[0].url == "https://example.com/hook"
        assert result.webhooks[1].url == "https://example.com/hook2"
        assert result.webhooks[1].design == "blink"


class TestDeleteWebhook:
    def test_delete_webhook(self) -> None:
        """DELETE /namespaces/{ns}/webhooks/{id} の正常系。"""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/v1/namespaces/myns/webhooks/10"
            return httpx.Response(204, content=b"", request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        # Should not raise
        client.delete_webhook("myns", 10)


class TestTestWebhook:
    def test_test_webhook(self) -> None:
        """POST /namespaces/{ns}/webhooks/{id}/test の正常系。"""
        body = {
            "delivered": True,
            "status_code": 200,
            "duration_ms": 120,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/namespaces/myns/webhooks/10/test"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.test_webhook("myns", 10)

        assert result.delivered is True
        assert result.status_code == 200
        assert result.duration_ms == 120


class TestListWebhookDeliveries:
    def test_list_webhook_deliveries(self) -> None:
        """GET /namespaces/{ns}/webhooks/{id}/deliveries の正常系。"""
        body = {
            "deliveries": [
                {
                    "id": "d-001",
                    "event": "design.published",
                    "status_code": 200,
                    "duration_ms": 95,
                    "delivered_at": _NOW,
                    "redelivery": False,
                },
                {
                    "id": "d-002",
                    "event": "design.yanked",
                    "status_code": 502,
                    "duration_ms": 5000,
                    "delivered_at": _NOW,
                    "redelivery": True,
                },
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/myns/webhooks/10/deliveries"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport, token="tok")

        result = client.list_webhook_deliveries("myns", 10)

        assert len(result.deliveries) == 2
        assert result.deliveries[0].id == "d-001"
        assert result.deliveries[0].event == "design.published"
        assert result.deliveries[1].id == "d-002"
        assert result.deliveries[1].redelivery is True


# ===========================================================================
# CLI-LICENSE-001: license_check client tests
# ===========================================================================


class TestLicenseCheck:
    def test_license_check_no_params(self) -> None:
        """GET /namespaces/{ns}/designs/{d}/versions/{v}/license-check クエリパラメータなし。"""
        body = {
            "design": "alice/counter",
            "version": "1.0.0",
            "tool_requirements": [
                {
                    "tool": "vivado",
                    "min_version": "2023.1",
                    "edition": "enterprise",
                    "required": True,
                    "note": "Synthesis",
                }
            ],
            "check": None,
            "disclaimer": (
                "FabricGate provides toolchain metadata only."
                " License compliance is the publisher's and user's responsibility."
            ),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/alice/designs/counter/versions/1.0.0/license-check"
            # No query params
            assert "tool" not in str(request.url.params)
            assert "edition" not in str(request.url.params)
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.license_check("alice", "counter", "1.0.0")

        assert result.design == "alice/counter"
        assert result.version == "1.0.0"
        assert len(result.tool_requirements) == 1
        assert result.tool_requirements[0].tool == "vivado"
        assert result.check is None

    def test_license_check_with_params(self) -> None:
        """GET /namespaces/{ns}/designs/{d}/versions/{v}/license-check tool/editionパラメータ付き。"""
        body = {
            "design": "alice/counter",
            "version": "1.0.0",
            "tool_requirements": [
                {
                    "tool": "vivado",
                    "min_version": "2023.1",
                    "edition": "enterprise",
                    "required": True,
                }
            ],
            "check": {
                "tool": "vivado",
                "edition": "enterprise",
                "meets_requirements": True,
                "notes": ["Vivado 2023.2 >= 2023.1"],
            },
            "disclaimer": (
                "FabricGate provides toolchain metadata only."
                " License compliance is the publisher's and user's responsibility."
            ),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/alice/designs/counter/versions/1.0.0/license-check"
            assert "vivado" in str(request.url.params)
            assert "enterprise" in str(request.url.params)
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.license_check("alice", "counter", "1.0.0", tool=["vivado"], edition="enterprise")

        assert result.design == "alice/counter"
        assert result.check is not None
        assert result.check.meets_requirements is True
        assert result.check.tool == "vivado"


# ===========================================================================
# CLI-DIFF-001: diff client tests
# ===========================================================================


class TestGetVersionDiff:
    def test_get_version_diff_with_platform(self) -> None:
        body = {
            "base": "1.0.0",
            "head": "2.0.0",
            "summary": {
                "platforms_added": [],
                "platforms_removed": [],
                "platforms_changed": ["xczu7ev/pynq"],
            },
            "diff": [
                {
                    "platform": "xczu7ev/pynq",
                    "fields": [
                        {"field": "bitstream_type", "base": None, "head": "partial"},
                    ],
                }
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/namespaces/alice/designs/counter/versions/2.0.0/diff"
            assert request.url.params.get("base") == "1.0.0"
            assert request.url.params.get("platform") == "xczu7ev/pynq"
            return httpx.Response(200, json=body, request=request)

        transport = httpx.MockTransport(handler)
        client = _make_client(transport)

        result = client.get_version_diff("alice", "counter", "2.0.0", "1.0.0", "xczu7ev/pynq")

        assert result.base == "1.0.0"
        assert result.head == "2.0.0"
        assert result.summary.platforms_changed == ["xczu7ev/pynq"]
