"""Tests for sdk_api.watch() — CLI-WATCH-001."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from fabricgate.models.api.responses import DesignDetailResponse, VersionSummary
from fabricgate.sdk import api as sdk_api

# ``watch`` is shadowed by the same-named function re-exported on the ``designs``
# package, so resolve the real submodule object (the monkeypatch target) via importlib.
_sdk_watch_mod = importlib.import_module("fabricgate.sdk.designs.watch")


def _make_version_summary(
    version: str,
    platforms: list[str] | None = None,
    yanked: bool = False,
) -> VersionSummary:
    return VersionSummary(
        version=version,  # type: ignore[arg-type]
        platforms=platforms or ["xc7z020/pynq"],  # type: ignore[arg-type]
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        yanked=yanked,
    )


def _make_design_detail(versions: list[VersionSummary]) -> DesignDetailResponse:
    return DesignDetailResponse(
        name="test-ns/blink",  # type: ignore[arg-type]
        versions=versions,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


class _WatchFakeClient:
    """Fake RegistryClient that returns a configurable DesignDetailResponse."""

    _response: DesignDetailResponse | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> _WatchFakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_design(self, namespace: str, design: str) -> DesignDetailResponse:
        assert namespace == "test-ns"
        assert design == "blink"
        assert _WatchFakeClient._response is not None
        return _WatchFakeClient._response


def _patch(monkeypatch: pytest.MonkeyPatch, client: type) -> None:
    monkeypatch.setattr(_sdk_watch_mod, "RegistryClient", client)


# ─────────────────────────────────────────────
# Existence check (no --since-version)
# ─────────────────────────────────────────────


def test_watch_no_since_version_returns_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail([_make_version_summary("1.2.0"), _make_version_summary("1.0.0")])
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(design_ref="test-ns/blink", registry="http://test")

    assert result.design_name == "test-ns/blink"
    assert result.new_version_found is False
    assert result.latest_version == "1.2.0"
    assert result.new_versions == []


# ─────────────────────────────────────────────
# --since-version: new version found
# ─────────────────────────────────────────────


def test_watch_new_version_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail(
        [
            _make_version_summary("2.0.0", platforms=["xc7z020/pynq"]),
            _make_version_summary("1.5.0", platforms=["xc7z020/pynq"]),
            _make_version_summary("1.0.0"),
        ]
    )
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(design_ref="test-ns/blink", since_version="1.0.0", registry="http://test")

    assert result.new_version_found is True
    assert result.latest_version == "2.0.0"
    assert "2.0.0" in result.new_versions
    assert "1.5.0" in result.new_versions


def test_watch_no_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail([_make_version_summary("1.0.0")])
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(design_ref="test-ns/blink", since_version="1.0.0", registry="http://test")

    assert result.new_version_found is False
    assert result.latest_version == "1.0.0"


# ─────────────────────────────────────────────
# Design not found → SDKError NOT_FOUND (CLI exit 1, ADR-008)
# ─────────────────────────────────────────────


def test_watch_design_not_found_raises_sdk_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import RegistryError
    from fabricgate.models.api.errors import ErrorDetail, ErrorResponse

    class _NotFoundClient(_WatchFakeClient):
        def get_design(self, namespace: str, design: str) -> DesignDetailResponse:  # type: ignore[override]
            raise RegistryError(
                404,
                ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="Design not found")),
            )

    _patch(monkeypatch, _NotFoundClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.watch(design_ref="test-ns/blink", registry="http://test")

    assert exc_info.value.code == sdk_api.ExitKind.NOT_FOUND


# ─────────────────────────────────────────────
# --platform filter
# ─────────────────────────────────────────────


def test_watch_platform_filter_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail(
        [
            _make_version_summary("2.0.0", platforms=["xc7z020/pynq", "xczu7ev/kv260"]),
            _make_version_summary("1.0.0", platforms=["xc7z020/pynq"]),
        ]
    )
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(
        design_ref="test-ns/blink",
        since_version="1.0.0",
        platform="xczu7ev/kv260",
        registry="http://test",
    )

    assert result.new_version_found is True
    assert result.latest_version == "2.0.0"


def test_watch_platform_filter_excludes_all(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail(
        [
            _make_version_summary("2.0.0", platforms=["xc7z020/pynq"]),
            _make_version_summary("1.0.0", platforms=["xc7z020/pynq"]),
        ]
    )
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(
        design_ref="test-ns/blink",
        since_version="1.0.0",
        platform="xczu7ev/kv260",
        registry="http://test",
    )

    assert result.new_version_found is False


# ─────────────────────────────────────────────
# --shell option
# ─────────────────────────────────────────────


def test_watch_shell_option_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail([_make_version_summary("3.0.0"), _make_version_summary("2.0.0")])
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(shell="test-ns/blink", since_version="2.0.0", registry="http://test")

    assert result.new_version_found is True
    assert result.latest_version == "3.0.0"


# ─────────────────────────────────────────────
# Mutual exclusion: design_ref AND shell
# ─────────────────────────────────────────────


def test_watch_both_ref_and_shell_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _WatchFakeClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.watch(
            design_ref="test-ns/blink",
            shell="test-ns/blink",
            registry="http://test",
        )

    assert "mutually exclusive" in str(exc_info.value).lower()


def test_watch_neither_ref_nor_shell_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _WatchFakeClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.watch(registry="http://test")

    assert "either" in str(exc_info.value).lower()


# ─────────────────────────────────────────────
# Yanked versions excluded
# ─────────────────────────────────────────────


def test_watch_yanked_versions_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    _WatchFakeClient._response = _make_design_detail(
        [
            _make_version_summary("2.0.0", yanked=True),
            _make_version_summary("1.0.0"),
        ]
    )
    _patch(monkeypatch, _WatchFakeClient)

    result = sdk_api.watch(design_ref="test-ns/blink", since_version="1.0.0", registry="http://test")

    # 2.0.0 is yanked, should not count as new
    assert result.new_version_found is False


# ─────────────────────────────────────────────
# _parse_semver_tuple — pre-release/build suffix
# ─────────────────────────────────────────────


def test_parse_semver_tuple_handles_prerelease() -> None:
    from fabricgate.sdk.designs.watch import _parse_semver_tuple

    assert _parse_semver_tuple("1.0.0") == (1, 0, 0)
    assert _parse_semver_tuple("2.3.4-beta.1") == (2, 3, 4)
    assert _parse_semver_tuple("1.0.0+build.42") == (1, 0, 0)
    assert _parse_semver_tuple("3.0.0-rc.1+sha.abc") == (3, 0, 0)


# ─────────────────────────────────────────────
# Network error → exit_code 4
# ─────────────────────────────────────────────


def test_watch_network_error_exit_code_4(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabricgate.client.registry_client import NetworkError

    class _NetworkErrorClient(_WatchFakeClient):
        def get_design(self, namespace: str, design: str) -> DesignDetailResponse:  # type: ignore[override]
            raise NetworkError("Network error: Connection refused")

    _patch(monkeypatch, _NetworkErrorClient)

    with pytest.raises(sdk_api.SDKError) as exc_info:
        sdk_api.watch(design_ref="test-ns/blink", registry="http://test")

    assert exc_info.value.code == sdk_api.ExitKind.INFRA
