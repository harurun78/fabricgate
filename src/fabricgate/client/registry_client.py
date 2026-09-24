"""HTTP client for FabricGate Registry API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from fabricgate.client.errors import FailureKind
from fabricgate.models.api.errors import ErrorDetail, ErrorResponse
from fabricgate.models.api.responses import (
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ArtifactUploadResponse,
    ArtifactUploadTicket,
    DependenciesResponse,
    DeprecateResponse,
    DesignDetailResponse,
    DesignStatsResponse,
    LicenseCheckResponse,
    LoginResponse,
    NamespaceResponse,
    NamespaceStatsResponse,
    OAuthTokenResponse,
    PublishResponse,
    QuotaResponse,
    SearchResponse,
    ShellResponse,
    VersionDetailResponse,
    VersionDiffResponse,
    VersionStatsResponse,
    WebhookCreateResponse,
    WebhookDeliveriesResponse,
    WebhookListResponse,
    WebhookTestResponse,
    YankResponse,
)


class RegistryError(Exception):
    """Raised when the registry returns an error response."""

    error: ErrorResponse | None

    def __init__(self, status_code: int, error: ErrorResponse) -> None:
        self.status_code = status_code
        self.error = error
        super().__init__(f"[{status_code}] {error.error.code}: {error.error.message}")

    @property
    def kind(self) -> FailureKind:
        """Semantic failure kind for this error (ADR-008, command-agnostic).

        Distilled from HTTP status + wire error code. Single source of truth;
        the SDK and CLI read this rather than re-deriving classification.
        """
        error_code = self.error.error.code if self.error else ""
        if self.status_code in (401, 403):
            return FailureKind.PERMISSION
        if self.status_code == 404:
            return FailureKind.NOT_FOUND
        if self.status_code == 409:
            if error_code == "DEPENDENCY_UNRESOLVABLE":
                return FailureKind.UNRESOLVABLE
            if error_code == "SHELL_NOT_FOUND":
                return FailureKind.SHELL_NOT_FOUND
            return FailureKind.INVALID
        if self.status_code in (400, 422, 429):
            return FailureKind.INVALID
        if self.status_code >= 500:
            return FailureKind.INFRA
        return FailureKind.GENERIC


class NetworkError(RegistryError):
    """Raised when a transport-layer failure prevents reaching the registry.

    Wraps an ``httpx`` transport error (connection refused, DNS failure,
    timeout) so callers only ever handle the :class:`RegistryError` hierarchy
    and ``httpx`` stays confined to this client layer.  Carries no HTTP status
    (``status_code = 0``, ``error = None``); its ``kind`` is ``FailureKind.INFRA``.
    """

    def __init__(self, message: str) -> None:
        self.status_code = 0
        self.error = None
        Exception.__init__(self, message)

    @property
    def kind(self) -> FailureKind:
        # Transport failure has no HTTP status (status_code == 0); classify
        # directly rather than falling through the base classifier to GENERIC.
        return FailureKind.INFRA


def _oauth_error_response(resp: httpx.Response) -> ErrorResponse | None:
    """Map a raw OAuth error body (RFC 6749 §5.2) onto the registry error envelope.

    ``{"error": "authorization_pending"}`` becomes code ``AUTHORIZATION_PENDING``,
    so a proxy that does not wrap OAuth errors cannot stall the device-flow poll.
    """
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("error"), str):
        return None
    description = body.get("error_description")
    return ErrorResponse(
        error=ErrorDetail(
            code=body["error"].upper(),
            message=description if isinstance(description, str) and description else body["error"],
        )
    )


def _part_content_type(field_name: str) -> str:
    """Return the appropriate MIME type for a multipart field.

    ``readme`` is included for future use when README upload is implemented.
    """
    if field_name in ("index", "readme") or field_name.endswith(":manifest"):
        return "application/x-yaml"
    return "application/octet-stream"


class RegistryClient:
    """Synchronous HTTP client for the FabricGate Registry API."""

    def __init__(
        self,
        base_url: str = "https://registry.fabricgate.dev/api/v1",
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RegistryClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ---- helpers ----

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kwargs)
            if resp.status_code >= 400:
                err: ErrorResponse | None
                try:
                    err = ErrorResponse.model_validate_json(resp.content)
                except Exception:
                    err = _oauth_error_response(resp)
                if err is None:
                    resp.raise_for_status()
                    raise AssertionError("unreachable: status >= 400")
                raise RegistryError(resp.status_code, err)
            return resp
        except httpx.HTTPError as exc:
            # Transport failures (connect/DNS/timeout) and the malformed-error-body
            # ``raise_for_status`` path both surface as ``httpx.HTTPError``.  Translate
            # them into ``NetworkError`` so ``httpx`` stays confined to this layer;
            # ``NetworkError.kind`` is ``FailureKind.INFRA``, as before.  Parseable
            # error responses raise ``RegistryError`` (not an httpx type) and pass through.
            raise NetworkError(f"Network error: {exc}") from exc

    # ---- Discovery ----

    def search_designs(
        self,
        q: str | None = None,
        platform: str | None = None,
        board: str | None = None,
        device_family: str | None = None,
        runtime: str | None = None,
        tag: str | None = None,
        page: int = 1,
        per_page: int = 20,
        namespace: str | None = None,
    ) -> SearchResponse:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if namespace:
            params["namespace"] = namespace
        if q:
            params["q"] = q
        if platform:
            params["platform"] = platform
        if board:
            params["board"] = board
        if device_family:
            params["device_family"] = device_family
        if runtime:
            params["runtime"] = runtime
        if tag:
            params["tag"] = tag
        resp = self._request("GET", "/designs", params=params)
        return SearchResponse.model_validate_json(resp.content)

    def get_design(self, namespace: str, design: str) -> DesignDetailResponse:
        resp = self._request("GET", f"/namespaces/{namespace}/designs/{design}")
        return DesignDetailResponse.model_validate_json(resp.content)

    def get_version(
        self,
        namespace: str,
        design: str,
        version: str,
    ) -> VersionDetailResponse:
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}",
        )
        return VersionDetailResponse.model_validate_json(resp.content)

    def get_platform_manifest_bytes(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
    ) -> bytes:
        """Download a Platform Manifest as raw bytes."""
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/platforms/{board_id}/{runtime}",
        )
        return resp.content

    def download_artifact(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
        filename: str,
    ) -> bytes:
        """Download an artifact file (follows redirects)."""
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}"
            f"/platforms/{board_id}/{runtime}/artifacts/{filename}",
            follow_redirects=True,
        )
        return resp.content

    # ---- Auth ----

    def device_authorization(self) -> dict[str, Any]:
        resp = self._request("POST", "/oauth/device_authorization")
        result: dict[str, Any] = resp.json()
        return result

    def token_exchange(self, **kwargs: str) -> LoginResponse:
        """Exchange a grant for a token.

        Accepts the OAuth token response the registry returns
        (``access_token`` / ``expires_in`` / ``scope``) and, as a tolerant
        reader, the flat ``{token, expires_at, scopes}`` shape.
        """
        resp = self._request("POST", "/oauth/token", json=kwargs)
        body = resp.json()
        if not (isinstance(body, dict) and "access_token" in body):
            return LoginResponse.model_validate_json(resp.content)
        oauth = OAuthTokenResponse.model_validate_json(resp.content)
        return LoginResponse(
            token=oauth.access_token,
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=oauth.expires_in),
            scopes=oauth.scope.split(),
            refresh_token=oauth.refresh_token,
        )

    # ---- Publish ----

    def create_artifact_uploads(
        self,
        namespace: str,
        design: str,
        artifacts: list[dict[str, Any]],
    ) -> ArtifactUploadResponse:
        """Ask the registry for presigned PUT URLs for *artifacts*.

        Each item is ``{"filename": str, "sha256": str, "size": int}``. A
        ticket with ``url=None`` means the registry already stores that
        content and the upload can be skipped.
        """
        resp = self._request(
            "POST",
            f"/namespaces/{namespace}/designs/{design}/uploads",
            json={"artifacts": artifacts},
        )
        return ArtifactUploadResponse.model_validate_json(resp.content)

    def upload_artifact(self, ticket: ArtifactUploadTicket, data: bytes) -> None:
        """PUT one artifact straight to object storage.

        Deliberately not routed through ``_request``: the URL is absolute and
        belongs to the storage provider, not the registry, and its errors are
        XML rather than the registry's JSON envelope.
        """
        if ticket.url is None:
            return
        try:
            resp = httpx.put(
                ticket.url,
                content=data,
                headers=ticket.headers,
                # No write deadline: a 256MB artifact on a slow uplink takes
                # far longer than the request timeout, and the upload is a
                # single PUT that cannot be resumed if it is cut off.
                timeout=httpx.Timeout(self._timeout, write=None),
            )
        except httpx.HTTPError as exc:
            raise NetworkError(f"Network error uploading {ticket.filename}: {exc}") from exc
        if resp.status_code >= 400:
            # 400 BadDigest means the bytes did not match the signed digest.
            raise NetworkError(
                f"Upload of {ticket.filename} failed with {resp.status_code}: {resp.text[:200]}",
            )

    def publish_version(
        self,
        namespace: str,
        design: str,
        version: str,
        files: dict[str, bytes],
    ) -> PublishResponse:
        """Publish a new version via multipart upload.

        ``platform:{pid}:artifact-url:{filename}`` entries carry a URL and go out
        as plain text fields; every other entry is a file part.
        """
        url_fields = {k: v.decode() for k, v in files.items() if ":artifact-url:" in k}
        multipart_files = [(k, (k, v, _part_content_type(k))) for k, v in files.items() if k not in url_fields]
        resp = self._request(
            "POST",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}",
            data=url_fields,
            files=multipart_files,
        )
        return PublishResponse.model_validate_json(resp.content)

    # ---- Yank ----

    def yank_version(
        self,
        namespace: str,
        design: str,
        version: str,
        reason: str = "",
    ) -> YankResponse:
        resp = self._request(
            "DELETE",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}",
            json={"reason": reason},
        )
        return YankResponse.model_validate_json(resp.content)

    def deprecate_version(
        self,
        namespace: str,
        design: str,
        version: str,
        message: str = "",
        successor: str | None = None,
    ) -> DeprecateResponse:
        """Set a design version to deprecated state."""
        body: dict[str, Any] = {"message": message}
        if successor:
            body["successor"] = successor
        resp = self._request(
            "POST",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/deprecate",
            json=body,
        )
        return DeprecateResponse.model_validate_json(resp.content)

    def undeprecate_version(
        self,
        namespace: str,
        design: str,
        version: str,
    ) -> DeprecateResponse:
        """Clear deprecated state from a design version."""
        resp = self._request(
            "DELETE",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/deprecate",
        )
        return DeprecateResponse.model_validate_json(resp.content)

    # ---- Namespace ----

    def list_namespaces(self) -> list[NamespaceResponse]:
        resp = self._request("GET", "/namespaces")
        return [NamespaceResponse.model_validate(ns) for ns in resp.json()]

    def get_namespace(self, namespace: str) -> NamespaceResponse:
        resp = self._request("GET", f"/namespaces/{namespace}")
        return NamespaceResponse.model_validate_json(resp.content)

    # ---- Dependencies ----

    def get_dependencies(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
        *,
        include_optional: bool = False,
    ) -> DependenciesResponse:
        """Fetch resolved dependency tree for a platform."""
        params: dict[str, Any] = {}
        if include_optional:
            params["include_optional"] = "true"
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/platforms/{board_id}/{runtime}/dependencies",
            params=params,
        )
        return DependenciesResponse.model_validate_json(resp.content)

    # ---- Shell ----

    def get_shell(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
    ) -> ShellResponse:
        """Fetch the static shell design for a partial bitstream."""
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/platforms/{board_id}/{runtime}/shell",
        )
        return ShellResponse.model_validate_json(resp.content)

    # ---- API Keys ----

    def create_api_key(
        self,
        name: str,
        scopes: list[str],
        expires_at: str | None = None,
    ) -> ApiKeyCreateResponse:
        """Create a new API key."""
        body: dict[str, Any] = {"name": name, "scopes": scopes}
        if expires_at:
            body["expires_at"] = expires_at
        resp = self._request("POST", "/users/me/api-keys", json=body)
        return ApiKeyCreateResponse.model_validate_json(resp.content)

    def list_api_keys(self) -> ApiKeyListResponse:
        """List all API keys for the current user."""
        resp = self._request("GET", "/users/me/api-keys")
        return ApiKeyListResponse.model_validate_json(resp.content)

    def delete_api_key(self, key_id: int) -> None:
        """Revoke an API key."""
        self._request("DELETE", f"/users/me/api-keys/{key_id}")

    # ---- Webhooks ----

    def create_webhook(
        self,
        namespace: str,
        url: str,
        events: list[str],
        design: str | None = None,
    ) -> WebhookCreateResponse:
        """Create a new webhook."""
        body: dict[str, Any] = {
            "url": url,
            "events": events,
        }
        if design:
            body["design"] = design
        resp = self._request("POST", f"/namespaces/{namespace}/webhooks", json=body)
        return WebhookCreateResponse.model_validate_json(resp.content)

    def list_webhooks(self, namespace: str) -> WebhookListResponse:
        """List all webhooks for a namespace."""
        resp = self._request("GET", f"/namespaces/{namespace}/webhooks")
        return WebhookListResponse.model_validate_json(resp.content)

    def delete_webhook(self, namespace: str, webhook_id: int) -> None:
        """Delete a webhook."""
        self._request("DELETE", f"/namespaces/{namespace}/webhooks/{webhook_id}")

    def test_webhook(self, namespace: str, webhook_id: int) -> WebhookTestResponse:
        """Send a test delivery to a webhook."""
        resp = self._request(
            "POST",
            f"/namespaces/{namespace}/webhooks/{webhook_id}/test",
        )
        return WebhookTestResponse.model_validate_json(resp.content)

    def list_webhook_deliveries(
        self,
        namespace: str,
        webhook_id: int,
        limit: int | None = None,
    ) -> WebhookDeliveriesResponse:
        """List delivery logs for a webhook."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/webhooks/{webhook_id}/deliveries",
            params=params,
        )
        return WebhookDeliveriesResponse.model_validate_json(resp.content)

    # ---- Version Diff ----

    def get_version_diff(
        self,
        namespace: str,
        design: str,
        version: str,
        base: str,
        platform: str | None = None,
    ) -> VersionDiffResponse:
        """Fetch metadata diff between two versions of a design."""
        params: dict[str, Any] = {"base": base}
        if platform:
            params["platform"] = platform
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/diff",
            params=params,
        )
        return VersionDiffResponse.model_validate_json(resp.content)

    # ---- License Check ----

    def license_check(
        self,
        namespace: str,
        design: str,
        version: str,
        tool: list[str] | None = None,
        edition: str | None = None,
    ) -> LicenseCheckResponse:
        """Check tool requirements for a design version."""
        params: dict[str, Any] = {}
        if tool:
            params["tool"] = tool
        if edition:
            params["edition"] = edition
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/license-check",
            params=params,
        )
        return LicenseCheckResponse.model_validate_json(resp.content)

    # ---- Download Stats ----

    def get_design_stats(
        self,
        namespace: str,
        design: str,
        *,
        period: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> DesignStatsResponse:
        """Fetch aggregated download stats for a design."""
        params: dict[str, Any] = {}
        if period:
            params["period"] = period
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/stats",
            params=params,
        )
        return DesignStatsResponse.model_validate_json(resp.content)

    def get_version_stats(
        self,
        namespace: str,
        design: str,
        version: str,
        *,
        period: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> VersionStatsResponse:
        """Fetch aggregated download stats for a design version."""
        params: dict[str, Any] = {}
        if period:
            params["period"] = period
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        resp = self._request(
            "GET",
            f"/namespaces/{namespace}/designs/{design}/versions/{version}/stats",
            params=params,
        )
        return VersionStatsResponse.model_validate_json(resp.content)

    def get_namespace_stats(self, namespace: str) -> NamespaceStatsResponse:
        """Fetch namespace-level download summary."""
        resp = self._request("GET", f"/namespaces/{namespace}/stats")
        return NamespaceStatsResponse.model_validate_json(resp.content)

    def get_namespace_quota(self, namespace: str) -> QuotaResponse:
        """Fetch namespace quota usage."""
        resp = self._request("GET", f"/namespaces/{namespace}/quota")
        return QuotaResponse.model_validate_json(resp.content)


@runtime_checkable
class RegistryClientProtocol(Protocol):
    """Stable client boundary for pull/push (G3).

    The minimum surface fabricgate's pull/push orchestration depends on
    (see docs/specs/client-behavior.md "client API boundary"). Any conformant
    object -- a test fake, or a future native/PyO3 client -- may be passed
    wherever a client is expected. Implementations MUST raise ``RegistryError``
    on HTTP error responses and ``NetworkError`` on transport failures, with
    the fields documented on those classes.
    """

    def get_version(self, namespace: str, design: str, version: str) -> VersionDetailResponse: ...

    def get_dependencies(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
        *,
        include_optional: bool = False,
    ) -> DependenciesResponse: ...

    def get_shell(self, namespace: str, design: str, version: str, board_id: str, runtime: str) -> ShellResponse: ...

    def get_platform_manifest_bytes(
        self, namespace: str, design: str, version: str, board_id: str, runtime: str
    ) -> bytes: ...

    def download_artifact(
        self,
        namespace: str,
        design: str,
        version: str,
        board_id: str,
        runtime: str,
        filename: str,
    ) -> bytes: ...

    def create_artifact_uploads(
        self, namespace: str, design: str, artifacts: list[dict[str, Any]]
    ) -> ArtifactUploadResponse: ...

    def upload_artifact(self, ticket: ArtifactUploadTicket, data: bytes) -> None: ...

    def publish_version(
        self, namespace: str, design: str, version: str, files: dict[str, bytes]
    ) -> PublishResponse: ...

    def get_namespace_quota(self, namespace: str) -> QuotaResponse: ...


if TYPE_CHECKING:
    # Static conformance: RegistryClient must satisfy RegistryClientProtocol.
    # mypy errors here (caught by `task verify`'s `mypy src`) if the concrete
    # client drifts from the boundary contract.
    def _assert_registry_client_conformance(
        c: RegistryClient,
    ) -> RegistryClientProtocol:
        return c
