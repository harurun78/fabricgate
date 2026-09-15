"""Unit tests for CLI commands."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from fabricgate.cli.main import main
from fabricgate.models.api.responses import (
    QuotaDesignsInfo,
    QuotaResponse,
    QuotaStorageInfo,
    QuotaVersionsInfo,
    VersionDiffField,
    VersionDiffPlatform,
    VersionDiffResponse,
    VersionDiffSummary,
)
from fabricgate.models.cli import (
    CacheEntry,
    DeprecateResult,
    DesignInfo,
    DesignStatsInfo,
    LicenseCheckInfo,
    LicenseCheckToolReq,
    LicenseCheckVerdict,
    LoginResult,
    NamespaceStatsInfo,
    PullResult,
    PushResult,
    SearchResult,
    StatsSeriesItem,
    StatsTopDesign,
    TokenCreateResult,
    TokenInfo,
    VerificationItem,
    VerificationResult,
    WatchResult,
    WebhookCreateResult,
    WebhookDeliveryItem,
    WebhookItem,
    WebhookTestResult,
    YankResult,
)
from fabricgate.models.design_index import PlatformEntry
from fabricgate.sdk import api as sdk_api


def test_search_json_output(monkeypatch) -> None:
    def _fake_search(*_args, **_kwargs):
        return [
            SearchResult(
                name="test-ns/blink",
                version="1.0.0",
                summary="Blink demo",
                platforms=["xc7z020/pynq"],
            )
        ]

    monkeypatch.setattr("fabricgate.cli.commands.search.sdk_api.search", _fake_search)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "search", "blink"])
    assert result.exit_code == 0
    assert '"name": "test-ns/blink"' in result.output


def test_search_text_output(monkeypatch) -> None:
    def _fake_search(*_args, **_kwargs):
        return [
            SearchResult(
                name="test-ns/blink",
                version="1.0.0",
                summary="Blink demo",
                platforms=["xc7z020/pynq", "xczu3eg/ultra96"],
            )
        ]

    monkeypatch.setattr("fabricgate.cli.commands.search.sdk_api.search", _fake_search)
    runner = CliRunner()
    result = runner.invoke(main, ["search", "blink"])
    assert result.exit_code == 0
    assert "test-ns/blink" in result.output
    assert "1.0.0" in result.output
    assert "xc7z020/pynq,xczu3eg/ultra96" in result.output
    assert "Blink demo" in result.output


def test_search_no_results(monkeypatch) -> None:
    monkeypatch.setattr("fabricgate.cli.commands.search.sdk_api.search", lambda *a, **k: [])
    runner = CliRunner()
    result = runner.invoke(main, ["search", "nothing"])
    assert result.exit_code == 0
    assert "No designs found." in result.output


def test_search_sdk_error(monkeypatch) -> None:
    def _raise(*_args, **_kwargs) -> None:
        raise sdk_api.SDKError("connection refused", code=sdk_api.ExitKind.INFRA)

    monkeypatch.setattr("fabricgate.cli.commands.search.sdk_api.search", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["search", "blink"])
    assert result.exit_code == 4
    assert "connection refused" in result.output


def test_info_text_output(monkeypatch) -> None:
    def _fake_info(*_args, **_kwargs):
        return DesignInfo(
            name="test-ns/blink",
            version="1.0.0",
            summary="Blink demo",
            platforms=[
                PlatformEntry(
                    platform="xc7z020/pynq",
                    digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.info.sdk_api.info", _fake_info)
    runner = CliRunner()
    result = runner.invoke(main, ["info", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "Name: test-ns/blink" in result.output


def test_verify_failure_uses_exit_code_3(monkeypatch, tmp_path: Path) -> None:
    def _fake_verify(*_args, **_kwargs):
        return VerificationResult(
            design_ref="test-ns/blink:1.0.0",
            platform="xc7z020/pynq",
            directory=str(tmp_path),
            artifacts=[VerificationItem(file="design.bit", sha256="deadbeef", verified=False)],
        )

    monkeypatch.setattr("fabricgate.cli.commands.verify.sdk_api.verify", _fake_verify)
    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(tmp_path)])
    assert result.exit_code == 3


def test_help_shows_global_options_and_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "--registry" in result.output
    assert "--platform" in result.output
    assert "--cache-dir" in result.output
    assert "--json" in result.output
    assert "pull" in result.output
    assert "push" in result.output
    assert "search" in result.output
    assert "verify" in result.output
    assert "info" in result.output
    assert "login" in result.output
    assert "stats" in result.output
    assert "quota" in result.output
    assert "deprecate" in result.output


def test_login_text_output(monkeypatch) -> None:
    def _fake_login(**_kwargs):
        return LoginResult(
            registry="https://registry.fabricgate.dev/api/v1",
            storage="OS keychain (registry.fabricgate.dev)",
        )

    monkeypatch.setattr("fabricgate.cli.commands.login.sdk_api.login", _fake_login)
    runner = CliRunner()
    result = runner.invoke(main, ["login"])
    assert result.exit_code == 0
    assert "Logged in" in result.output
    assert "OS keychain" in result.output


def test_login_json_output(monkeypatch) -> None:
    def _fake_login(**_kwargs):
        return LoginResult(
            registry="https://registry.fabricgate.dev/api/v1",
            storage="OS keychain (registry.fabricgate.dev)",
        )

    monkeypatch.setattr("fabricgate.cli.commands.login.sdk_api.login", _fake_login)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "login"])
    assert result.exit_code == 0
    assert '"registry":' in result.output
    assert '"storage":' in result.output


def test_login_with_registry_option(monkeypatch) -> None:
    captured_kwargs: dict = {}

    def _fake_login(**kwargs):
        captured_kwargs.update(kwargs)
        return LoginResult(
            registry=kwargs.get("registry", "https://example.com/api/v1"),
            storage="file",
        )

    monkeypatch.setattr("fabricgate.cli.commands.login.sdk_api.login", _fake_login)
    runner = CliRunner()
    result = runner.invoke(main, ["login", "--registry", "https://custom.example.com/api/v1"])
    assert result.exit_code == 0
    assert captured_kwargs["registry"] == "https://custom.example.com/api/v1"


def test_login_sdk_error(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_login(**_kwargs):
        raise SDKError("connection refused")

    monkeypatch.setattr("fabricgate.cli.commands.login.sdk_api.login", _fake_login)
    runner = CliRunner()
    result = runner.invoke(main, ["login"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------

_PUSH_RESULT = PushResult(
    name="test-ns/blink",
    version="1.0.0",
    platforms=["xc7z020/pynq", "xc7z020/linux-fpgamgr"],
    published_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def test_push_text_output(monkeypatch, tmp_path) -> None:
    def _fake_push(*_args, **_kwargs):
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])
    assert result.exit_code == 0
    assert "Published: test-ns/blink:1.0.0 (2 platforms)" in result.output


def test_push_warning_output(monkeypatch, tmp_path) -> None:
    def _fake_push(*_args, **_kwargs):
        payload = _PUSH_RESULT.model_dump()
        payload["quota_warning"] = "上限に近づいています"
        return PushResult(**payload)

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])
    assert result.exit_code == 0
    assert "⚠" in result.stderr
    assert "上限に近づいています" in result.stderr


def test_push_json_output(monkeypatch, tmp_path) -> None:
    def _fake_push(*_args, **_kwargs):
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "push", str(tmp_path)])
    assert result.exit_code == 0
    assert '"name": "test-ns/blink"' in result.output
    assert '"platforms"' in result.output


def test_push_with_namespace_option(monkeypatch, tmp_path) -> None:
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path), "--namespace", "custom-ns"])
    assert result.exit_code == 0
    assert captured_kwargs["namespace"] == "custom-ns"


def test_push_sdk_error(monkeypatch, tmp_path) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_push(*_args, **_kwargs):
        raise SDKError("Digest mismatch for design.bit", code=sdk_api.ExitKind.INVALID)

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])
    assert result.exit_code == 3


def test_push_cmd_shows_sha_warning(monkeypatch, tmp_path) -> None:
    """sha_warning in PushResult causes '⚠ Warning:' to appear in stderr."""
    _sha_warn = "Artifact design.bit has a placeholder sha256 — run with real bitstream"

    def _fake_push(*_args, **_kwargs):
        payload = _PUSH_RESULT.model_dump()
        payload["sha_warning"] = _sha_warn
        return PushResult(**payload)

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])
    assert result.exit_code == 0
    assert "⚠ Warning:" in result.stderr


def test_push_cmd_skip_sha_check_flag(monkeypatch, tmp_path) -> None:
    """--skip-sha-check flag is forwarded to sdk_api.push as skip_sha_check=True."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path), "--skip-sha-check"])
    assert result.exit_code == 0
    assert captured_kwargs.get("skip_sha_check") is True


# ---------------------------------------------------------------------------
# push — board promotion (CLI-PUSH-002)
# ---------------------------------------------------------------------------

from fabricgate.cli.commands.push import _PlatformInfo  # noqa: E402

_CUSTOM_AXI_INFO = _PlatformInfo(
    board_id="custom-xczu7ev",
    runtime="pynq",
    device_family="xczu7ev",
    design_portability="axi-only",
)
_CUSTOM_BOARD_SPECIFIC_INFO = _PlatformInfo(
    board_id="custom-xczu7ev",
    runtime="pynq",
    device_family="xczu7ev",
    design_portability="board-specific",
)
_REGULAR_INFO = _PlatformInfo(
    board_id="zcu104",
    runtime="pynq",
    device_family="xczu7ev",
    design_portability="axi-only",
)


def test_push_custom_axi_yes_flag(monkeypatch, tmp_path) -> None:
    """--yes promotes axi-only custom design to generic-*."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: _CUSTOM_AXI_INFO)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path), "--yes"])

    assert result.exit_code == 0
    assert "Pushed as generic-xczu7ev/pynq" in result.output
    assert captured_kwargs.get("board_override") == "generic-xczu7ev"


def test_push_custom_axi_tty_prompt_yes(monkeypatch, tmp_path) -> None:
    """TTY + y input → promotion accepted."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: _CUSTOM_AXI_INFO)
    monkeypatch.setattr("fabricgate.cli.commands.push._is_tty", lambda: True)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)], input="y\n")

    assert result.exit_code == 0
    assert "Pushed as generic-xczu7ev/pynq" in result.output
    assert captured_kwargs.get("board_override") == "generic-xczu7ev"


def test_push_custom_axi_tty_prompt_no(monkeypatch, tmp_path) -> None:
    """TTY + N input → normal push (no promotion)."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: _CUSTOM_AXI_INFO)
    monkeypatch.setattr("fabricgate.cli.commands.push._is_tty", lambda: True)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)], input="N\n")

    assert result.exit_code == 0
    assert "Published:" in result.output
    assert captured_kwargs.get("board_override") is None


def test_push_custom_axi_non_tty_auto_n(monkeypatch, tmp_path) -> None:
    """Non-TTY → info message shown, push proceeds without promotion."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: _CUSTOM_AXI_INFO)
    monkeypatch.setattr("fabricgate.cli.commands.push._is_tty", lambda: False)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])

    assert result.exit_code == 0
    assert "Info:" in result.output
    assert "generic-xczu7ev/pynq" in result.output
    assert captured_kwargs.get("board_override") is None


def test_push_yes_flag_board_specific_error(monkeypatch, tmp_path) -> None:
    """--yes + board-specific design → error, no SDK call."""
    push_called = False

    def _fake_push(*_args, **_kwargs):
        nonlocal push_called
        push_called = True
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr(
        "fabricgate.cli.commands.push._detect_platform_info",
        lambda _: _CUSTOM_BOARD_SPECIFIC_INFO,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path), "--yes"])

    assert result.exit_code == 1
    assert "--yes requires axi-only design" in result.output + result.stderr_bytes.decode()
    assert not push_called


def test_push_non_custom_board_no_prompt(monkeypatch, tmp_path) -> None:
    """Regular board (not custom-*) → no promotion logic, normal push."""
    captured_kwargs: dict = {}

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: _REGULAR_INFO)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path)])

    assert result.exit_code == 0
    assert "Published:" in result.output
    assert captured_kwargs.get("board_override") is None


def test_push_custom_axi_no_device_family_fallback(monkeypatch, tmp_path) -> None:
    """When device_family is None, fall back to board_id suffix."""
    captured_kwargs: dict = {}
    no_family_info = _PlatformInfo(
        board_id="custom-xczu7ev", runtime="pynq", device_family=None, design_portability="axi-only"
    )

    def _fake_push(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _PUSH_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.push.sdk_api.push", _fake_push)
    monkeypatch.setattr("fabricgate.cli.commands.push._detect_platform_info", lambda _: no_family_info)

    runner = CliRunner()
    result = runner.invoke(main, ["push", str(tmp_path), "--yes"])

    assert result.exit_code == 0
    assert "Pushed as generic-xczu7ev/pynq" in result.output
    assert captured_kwargs.get("board_override") == "generic-xczu7ev"


# ---------------------------------------------------------------------------
# push — direct helper tests (_is_tty, _detect_platform_info)
# ---------------------------------------------------------------------------


def test_is_tty_returns_bool() -> None:
    """_is_tty() は bool を返す (line 25)。"""
    from fabricgate.cli.commands.push import _is_tty

    result = _is_tty()
    assert isinstance(result, bool)


def test_detect_platform_info_no_platforms(monkeypatch, tmp_path) -> None:
    """platforms が空のとき None を返す (lines 43-44)。"""
    from fabricgate.cli.commands.push import _detect_platform_info

    mock_index = type("Index", (), {"platforms": []})()
    monkeypatch.setattr("fabricgate.client.publisher.load_design_index", lambda _: (mock_index, None))
    assert _detect_platform_info(tmp_path) is None


def test_detect_platform_info_no_slash(monkeypatch, tmp_path) -> None:
    """platform に '/' がないとき None を返す (lines 47-48)。"""
    from fabricgate.cli.commands.push import _detect_platform_info

    entry = type("Entry", (), {"platform": "noslash"})()
    mock_index = type("Index", (), {"platforms": [entry]})()
    monkeypatch.setattr("fabricgate.client.publisher.load_design_index", lambda _: (mock_index, None))
    assert _detect_platform_info(tmp_path) is None


def test_detect_platform_info_no_manifest(monkeypatch, tmp_path) -> None:
    """manifest.yaml が存在しないとき device_family=None の _PlatformInfo を返す (line 55)。"""
    from fabricgate.cli.commands.push import _detect_platform_info

    entry = type("Entry", (), {"platform": "xczu7ev/pynq"})()
    mock_index = type("Index", (), {"platforms": [entry]})()
    monkeypatch.setattr("fabricgate.client.publisher.load_design_index", lambda _: (mock_index, None))
    result = _detect_platform_info(tmp_path)
    assert result is not None
    assert result.board_id == "xczu7ev"
    assert result.runtime == "pynq"
    assert result.device_family is None
    assert result.design_portability is None


def test_detect_platform_info_invalid_manifest(monkeypatch, tmp_path) -> None:
    """manifest.yaml の pydantic parse 失敗時に device_family=None の _PlatformInfo を返す (lines 59-60)。"""
    from fabricgate.cli.commands.push import _detect_platform_info

    entry = type("Entry", (), {"platform": "xczu7ev/pynq"})()
    mock_index = type("Index", (), {"platforms": [entry]})()
    monkeypatch.setattr("fabricgate.client.publisher.load_design_index", lambda _: (mock_index, None))
    manifest_dir = tmp_path / "xczu7ev" / "pynq"
    manifest_dir.mkdir(parents=True)
    # Valid YAML but unknown runtime → pydantic ValidationError
    (manifest_dir / "manifest.yaml").write_text(
        "schema: fabricgate-platform/v1\nruntime: unknown-runtime\nboard: zcu104\n"
    )
    result = _detect_platform_info(tmp_path)
    assert result is not None
    assert result.device_family is None


def test_detect_platform_info_valid_manifest(monkeypatch, tmp_path) -> None:
    """有効な manifest.yaml から device_family を読み取る (lines 62-66)。"""
    from pathlib import Path as _Path

    from fabricgate.cli.commands.push import _detect_platform_info

    entry = type("Entry", (), {"platform": "zcu104/pynq"})()
    mock_index = type("Index", (), {"platforms": [entry]})()
    monkeypatch.setattr("fabricgate.client.publisher.load_design_index", lambda _: (mock_index, None))
    manifest_dir = tmp_path / "zcu104" / "pynq"
    manifest_dir.mkdir(parents=True)
    fixtures = _Path(__file__).resolve().parent.parent / "fixtures"
    (manifest_dir / "manifest.yaml").write_text((fixtures / "sample_manifest.yaml").read_text())
    result = _detect_platform_info(tmp_path)
    assert result is not None
    assert result.board_id == "zcu104"
    assert result.runtime == "pynq"
    assert result.device_family == "xczu7ev"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

_LIST_ENTRIES = [
    CacheEntry(
        name="fabricgate/blink",
        version="1.0.0",
        platform="xczu7ev/pynq",
        path="/tmp/cache/fabricgate/blink/1.0.0/xczu7ev/pynq",
        pulled_at=datetime(2026, 3, 17, tzinfo=UTC),
        digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ),
    CacheEntry(
        name="xilinx/axi-dma-demo",
        version="2.0.1",
        platform="xczu7ev/linux-fpgamgr",
        path="/tmp/cache/xilinx/axi-dma-demo/2.0.1/xczu7ev/linux-fpgamgr",
        pulled_at=datetime(2026, 3, 16, tzinfo=UTC),
        digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ),
]


def test_list_text_output(monkeypatch, tmp_path: Path) -> None:
    from fabricgate.models.cli import CacheIndex

    def _fake_load(cache_dir=None):
        return CacheIndex(entries=_LIST_ENTRIES)

    monkeypatch.setattr("fabricgate.cli.commands.list_cmd.load_index", _fake_load)
    runner = CliRunner()
    result = runner.invoke(main, ["--cache-dir", str(tmp_path), "list"])
    assert result.exit_code == 0
    assert "DESIGN" in result.output
    assert "fabricgate/blink" in result.output
    assert "xczu7ev/pynq" in result.output
    assert "2026-03-17" in result.output
    assert "xilinx/axi-dma-demo" in result.output


def test_list_json_output(monkeypatch, tmp_path: Path) -> None:
    from fabricgate.models.cli import CacheIndex

    def _fake_load(cache_dir=None):
        return CacheIndex(entries=_LIST_ENTRIES)

    monkeypatch.setattr("fabricgate.cli.commands.list_cmd.load_index", _fake_load)
    runner = CliRunner()
    result = runner.invoke(main, ["--cache-dir", str(tmp_path), "--json", "list"])
    assert result.exit_code == 0
    assert '"name": "fabricgate/blink"' in result.output
    assert '"platform": "xczu7ev/pynq"' in result.output


def test_list_empty_cache(monkeypatch, tmp_path: Path) -> None:
    from fabricgate.models.cli import CacheIndex

    def _fake_load(cache_dir=None):
        return CacheIndex()

    monkeypatch.setattr("fabricgate.cli.commands.list_cmd.load_index", _fake_load)
    runner = CliRunner()
    result = runner.invoke(main, ["--cache-dir", str(tmp_path), "list"])
    assert result.exit_code == 0
    assert "No cached designs." in result.output


def test_list_json_empty_cache(monkeypatch, tmp_path: Path) -> None:
    from fabricgate.models.cli import CacheIndex

    def _fake_load(cache_dir=None):
        return CacheIndex()

    monkeypatch.setattr("fabricgate.cli.commands.list_cmd.load_index", _fake_load)
    runner = CliRunner()
    result = runner.invoke(main, ["--cache-dir", str(tmp_path), "--json", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_list_appears_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.output


# ===========================================================================
# CLI-STATS-001: stats command
# ===========================================================================


def test_stats_design_text_output(monkeypatch) -> None:
    def _fake_stats(**_kwargs):
        return DesignStatsInfo(
            name="alice/fpga-uart",
            version=None,
            total_downloads=4821,
            period="daily",
            series=[
                StatsSeriesItem(date="2026-03-25", downloads=42),
                StatsSeriesItem(date="2026-03-26", downloads=67),
                StatsSeriesItem(date="2026-03-27", downloads=55),
            ],
            last_7d=384,
            last_30d=1621,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "alice/fpga-uart"])

    assert result.exit_code == 0
    assert "alice/fpga-uart  (total: 4,821 downloads)" in result.output
    assert "Daily downloads" in result.output
    assert "2026-03-26" in result.output
    assert "#" in result.output
    assert "Last 7d: 384" in result.output
    assert "Last 30d: 1,621" in result.output


def test_stats_design_options_are_forwarded(monkeypatch) -> None:
    captured: dict = {}

    def _fake_stats(**kwargs):
        captured.update(kwargs)
        return DesignStatsInfo(
            name="alice/fpga-uart",
            version="1.2.0",
            total_downloads=1203,
            period="weekly",
            series=[StatsSeriesItem(date="2026-03-01", downloads=200)],
            last_7d=200,
            last_30d=200,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "stats",
            "alice/fpga-uart",
            "--period",
            "weekly",
            "--from",
            "2026-03-01",
            "--to",
            "2026-03-31",
            "--version",
            "1.2.0",
        ],
    )

    assert result.exit_code == 0
    assert captured["design_ref"] == "alice/fpga-uart"
    assert captured["period"] == "weekly"
    assert captured["from_date"] == "2026-03-01"
    assert captured["to_date"] == "2026-03-31"
    assert captured["version"] == "1.2.0"


def test_stats_namespace_text_output(monkeypatch) -> None:
    def _fake_stats(**_kwargs):
        return NamespaceStatsInfo(
            namespace="alice",
            total_downloads=12480,
            top_designs=[
                StatsTopDesign(name="alice/fpga-uart", total_downloads=4821),
                StatsTopDesign(name="alice/axi-bridge", total_downloads=3902),
            ],
            last_7d=384,
            last_30d=1621,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "--namespace", "alice"])

    assert result.exit_code == 0
    assert "Namespace: alice  (total: 12,480 downloads)" in result.output
    assert "Top designs:" in result.output
    assert "alice/fpga-uart" in result.output
    assert "Last 7d: 384" in result.output


def test_stats_requires_exactly_one_target() -> None:
    runner = CliRunner()

    result_none = runner.invoke(main, ["stats"])
    assert result_none.exit_code == 2
    assert "Specify exactly one target" in result_none.output

    result_both = runner.invoke(main, ["stats", "alice/fpga-uart", "--namespace", "alice"])
    assert result_both.exit_code == 2
    assert "Specify exactly one target" in result_both.output


def test_quota_text_output(monkeypatch) -> None:
    def _fake_quota(**_kwargs):
        return QuotaResponse(
            namespace="alice",
            storage=QuotaStorageInfo(used_bytes=1_073_741_824, limit_bytes=5_368_709_120, used_percent=20.0),
            versions_per_design=QuotaVersionsInfo(limit=100),
            designs=QuotaDesignsInfo(used=12, limit=200),
            file_size_limit_bytes=524_288_000,
        )

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota)
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "--namespace", "alice"])
    assert result.exit_code == 0
    assert "Namespace: alice" in result.output
    assert "Storage" in result.output
    assert "Designs" in result.output
    assert "Versions / design limit: 100" in result.output


def test_quota_warning_output(monkeypatch) -> None:
    def _fake_quota(**_kwargs):
        return QuotaResponse(
            namespace="alice",
            storage=QuotaStorageInfo(used_bytes=4_724_464_640, limit_bytes=5_368_709_120, used_percent=88.0),
            versions_per_design=QuotaVersionsInfo(limit=100),
            designs=QuotaDesignsInfo(used=12, limit=200),
            file_size_limit_bytes=524_288_000,
        )

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota)
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "--namespace", "alice"])
    assert result.exit_code == 0
    assert "⚠" in result.output
    assert "上限に近づいています" in result.output


def test_quota_json_output(monkeypatch) -> None:
    def _fake_quota(**_kwargs):
        return QuotaResponse(
            namespace="alice",
            storage=QuotaStorageInfo(used_bytes=1, limit_bytes=10, used_percent=10.0),
            versions_per_design=QuotaVersionsInfo(limit=100),
            designs=QuotaDesignsInfo(used=1, limit=200),
            file_size_limit_bytes=524_288_000,
        )

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "quota", "--namespace", "alice"])
    assert result.exit_code == 0
    assert '"namespace": "alice"' in result.output
    assert '"used_percent": 10.0' in result.output


def test_quota_exit_code_propagation(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_quota_forbidden(**_kwargs):
        raise SDKError("forbidden", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota_forbidden)
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "--namespace", "private"])
    assert result.exit_code == 2

    def _fake_quota_not_found(**_kwargs):
        raise SDKError("missing", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota_not_found)
    result = runner.invoke(main, ["quota", "--namespace", "missing"])
    assert result.exit_code == 1


def test_stats_exit_code_propagation(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_stats_permission(**_kwargs):
        raise SDKError("forbidden", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats_permission)
    runner = CliRunner()
    result_permission = runner.invoke(main, ["stats", "--namespace", "private"])
    assert result_permission.exit_code == 2

    def _fake_stats_not_found(**_kwargs):
        raise SDKError("missing", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats_not_found)
    result_not_found = runner.invoke(main, ["stats", "alice/missing"])
    assert result_not_found.exit_code == 1


# ===========================================================================
# CLI-PULL-002: pull command — deps, shell, deprecated, exit codes
# ===========================================================================


_PULL_RESULT = PullResult(
    name="test-ns/blink",
    version="1.0.0",
    platform="xc7z020/pynq",
    path="/tmp/output/blink-1.0.0",
    artifacts=["design.bit", "design.hwh"],
    cached=False,
    dependencies=["dep-ns/dep-design:0.1.0"],
    shell="shell-ns/shell-design:2.0.0",
)


def test_pull_text_output(monkeypatch, tmp_path) -> None:
    """基本的なpull成功のテキスト出力。"""

    def _fake_pull(*_args, **_kwargs):
        return _PULL_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "Saved to" in result.output
    assert "design.bit" in result.output
    assert "Dependencies:" in result.output
    assert "dep-ns/dep-design:0.1.0" in result.output
    assert "Shell: shell-ns/shell-design:2.0.0" in result.output


def test_pull_family_fallback_shows_provenance(monkeypatch, tmp_path) -> None:
    """family fallback発動時にSelected行で由来が表示される。"""

    def _fake_pull(*_args, **_kwargs):
        return PullResult(
            name="fabricgate/hello",
            version="1.0.0",
            platform="generic-xc7z020/pynq",
            path="/tmp/output/hello-1.0.0",
            artifacts=["design.bit", "design.hwh"],
            cached=False,
            fallback_from="pynq-z2/pynq",
        )

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "--platform", "pynq-z2/pynq", "fabricgate/hello:1.0.0"])
    assert result.exit_code == 0
    assert "Selected: generic-xc7z020/pynq (family fallback from pynq-z2/pynq)" in result.output
    assert "Saved to" in result.output


def test_pull_exact_match_no_fallback_line(monkeypatch, tmp_path) -> None:
    """完全一致時はfamily fallback行を出さない。"""

    def _fake_pull(*_args, **_kwargs):
        return _PULL_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "family fallback" not in result.output


def test_pull_no_deps_option(monkeypatch, tmp_path) -> None:
    """--no-depsがSDKに渡される。"""
    captured_kwargs: dict = {}

    def _fake_pull(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return PullResult(
            name="test-ns/blink",
            version="1.0.0",
            platform="xc7z020/pynq",
            path="/tmp/out",
            artifacts=["design.bit"],
            cached=False,
        )

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "--no-deps", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert captured_kwargs["no_deps"] is True


def test_pull_deps_only_option(monkeypatch, tmp_path) -> None:
    """--deps-onlyがSDKに渡される。"""
    captured_kwargs: dict = {}

    def _fake_pull(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return PullResult(
            name="test-ns/blink",
            version="1.0.0",
            platform="xc7z020/pynq",
            path="/tmp/out",
            artifacts=[],
            cached=False,
            dependencies=["dep-ns/dep-design:0.1.0"],
        )

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "--deps-only", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert captured_kwargs["deps_only"] is True


def test_pull_no_shell_option_shows_warning(monkeypatch, tmp_path) -> None:
    """--no-shellで警告がstderrに出る。"""

    def _fake_pull(*_args, **kwargs):
        return PullResult(
            name="test-ns/blink",
            version="1.0.0",
            platform="xc7z020/pynq",
            path="/tmp/out",
            artifacts=["design.bit"],
            cached=False,
        )

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "--no-shell", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "\u26a0" in result.stderr
    assert "Shell dependency skipped" in result.stderr


def test_pull_deprecated_shows_warning(monkeypatch, tmp_path) -> None:
    """deprecated版pull時に⚠警告がstderrに表示される。"""
    deprecated_result = PullResult(
        name="test-ns/blink",
        version="1.0.0",
        platform="xc7z020/pynq",
        path="/tmp/out",
        artifacts=["design.bit"],
        cached=False,
        deprecated_warning="test-ns/blink:1.0.0 is deprecated. Use test-ns/blink:2.0.0 instead.",
    )

    def _fake_pull(*_args, **_kwargs):
        return deprecated_result

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "test-ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "\u26a0" in result.stderr
    assert "deprecated" in result.stderr


def test_pull_exit_code_5(monkeypatch, tmp_path) -> None:
    """DEPENDENCY_UNRESOLVABLEのexit code 5。"""
    from fabricgate.sdk.api import SDKError

    def _fake_pull(*_args, **_kwargs):
        raise SDKError("Cannot resolve deps", code=sdk_api.ExitKind.UNRESOLVABLE)

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "test-ns/blink:1.0.0"])
    assert result.exit_code == 5


def test_pull_exit_code_6(monkeypatch, tmp_path) -> None:
    """SHELL_NOT_FOUNDのexit code 6。"""
    from fabricgate.sdk.api import SDKError

    def _fake_pull(*_args, **_kwargs):
        raise SDKError("Shell not found", code=sdk_api.ExitKind.SHELL_NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["pull", "test-ns/blink:1.0.0"])
    assert result.exit_code == 6


# ===========================================================================
# CLI-TOKEN-001: token command — create, list, revoke
# ===========================================================================


_TOKEN_CREATE_RESULT = TokenCreateResult(
    id=42,
    name="ci-key",
    key="fgk_abc123secrettoken",
    scopes=["public:read"],
    expires_at=datetime(2027, 1, 1, tzinfo=UTC),
)

_TOKEN_LIST_ITEMS = [
    TokenInfo(
        id=1,
        name="key-alpha",
        scopes=["public:read"],
        expires_at=datetime(2027, 6, 1, tzinfo=UTC),
        last_used_at=datetime(2026, 3, 28, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    ),
    TokenInfo(
        id=2,
        name="key-beta",
        scopes=["public:read", "ns:alice:write"],
        expires_at=None,
        last_used_at=None,
        created_at=datetime(2026, 2, 15, tzinfo=UTC),
    ),
]


def test_token_create_text_output(monkeypatch) -> None:
    """token create成功のテキスト出力 — トークン文字列が表示される。"""

    def _fake_token_create(**_kwargs):
        return _TOKEN_CREATE_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_create", _fake_token_create)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "create", "--name", "ci-key"])
    assert result.exit_code == 0
    assert "ci-key" in result.output
    assert "fgk_abc123secrettoken" in result.output
    assert "public:read" in result.output


def test_token_create_json_output(monkeypatch) -> None:
    """token create成功のJSON出力。"""

    def _fake_token_create(**_kwargs):
        return _TOKEN_CREATE_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_create", _fake_token_create)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "token", "create", "--name", "ci-key"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "ci-key"
    assert data["key"] == "fgk_abc123secrettoken"
    assert data["scopes"] == ["public:read"]


def test_token_create_auth_error(monkeypatch) -> None:
    """未認証時にexit code 2。"""
    from fabricgate.sdk.api import SDKError

    def _fake_token_create(**_kwargs):
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_create", _fake_token_create)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "create", "--name", "ci-key"])
    assert result.exit_code == 2


def test_token_list_text_output(monkeypatch) -> None:
    """token list — 2件のキーがテーブル形式で表示される。"""

    def _fake_token_list(**_kwargs):
        return _TOKEN_LIST_ITEMS

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_list", _fake_token_list)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "list"])
    assert result.exit_code == 0
    assert "key-alpha" in result.output
    assert "key-beta" in result.output
    assert "ID" in result.output
    assert "NAME" in result.output


def test_token_list_json_output(monkeypatch) -> None:
    """token list — JSON出力。"""

    def _fake_token_list(**_kwargs):
        return _TOKEN_LIST_ITEMS

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_list", _fake_token_list)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "token", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["name"] == "key-alpha"
    assert data[1]["name"] == "key-beta"


def test_token_list_empty(monkeypatch) -> None:
    """キーが0件のとき「No API keys found.」メッセージ。"""

    def _fake_token_list(**_kwargs):
        return []

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_list", _fake_token_list)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "list"])
    assert result.exit_code == 0
    assert "No API keys found." in result.output


def test_token_revoke_success(monkeypatch) -> None:
    """--forceでtoken revoke成功、exit 0。"""

    def _fake_token_revoke(*_args, **_kwargs):
        return None

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", _fake_token_revoke)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "revoke", "42", "--force"])
    assert result.exit_code == 0
    assert "Revoked" in result.output


def test_token_revoke_not_found(monkeypatch) -> None:
    """存在しないキーでexit code 1。"""
    from fabricgate.sdk.api import SDKError

    def _fake_token_revoke(*_args, **_kwargs):
        raise SDKError("[404] NOT_FOUND: API key not found", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", _fake_token_revoke)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "revoke", "999", "--force"])
    assert result.exit_code == 1


def test_token_revoke_confirmation_abort(monkeypatch) -> None:
    """確認プロンプトでNを入力するとexit 0でキャンセル。"""

    def _fake_token_revoke(*_args, **_kwargs):
        raise AssertionError("revoke should not be called")

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", _fake_token_revoke)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "revoke", "42"], input="N\n")
    assert result.exit_code == 0


# ===========================================================================
# CLI-WEBHOOK-001: webhook command — create, list, delete, test, deliveries
# ===========================================================================


_WEBHOOK_CREATE_RESULT = WebhookCreateResult(
    id=10,
    url="https://example.com/hook",
    events=["design.published", "design.yanked"],
    design=None,
    secret="whsec_abcdef1234567890",
    status="active",
    created_at=datetime(2026, 3, 29, tzinfo=UTC),
)

_WEBHOOK_LIST_ITEMS = [
    WebhookItem(
        id=10,
        url="https://example.com/hook",
        events=["design.published"],
        design=None,
        status="active",
        last_delivered_at=datetime(2026, 3, 28, tzinfo=UTC),
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    ),
    WebhookItem(
        id=11,
        url="https://example.com/hook2",
        events=["design.published", "design.yanked"],
        design="blink",
        status="active",
        last_delivered_at=None,
        created_at=datetime(2026, 3, 15, tzinfo=UTC),
    ),
]

_WEBHOOK_TEST_SUCCESS = WebhookTestResult(
    delivered=True,
    status_code=200,
    duration_ms=120,
)

_WEBHOOK_TEST_FAILURE = WebhookTestResult(
    delivered=False,
    status_code=500,
    duration_ms=3000,
)

_WEBHOOK_DELIVERIES = [
    WebhookDeliveryItem(
        id="d-001",
        event="design.published",
        status_code=200,
        duration_ms=95,
        delivered_at=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
        redelivery=False,
    ),
    WebhookDeliveryItem(
        id="d-002",
        event="design.yanked",
        status_code=502,
        duration_ms=5000,
        delivered_at=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        redelivery=True,
    ),
]


def test_webhook_create_text_output(monkeypatch) -> None:
    """webhook create成功のテキスト出力 — URL, events, secret, 警告が表示される。"""

    def _fake_webhook_create(**_kwargs):
        return _WEBHOOK_CREATE_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "webhook",
            "create",
            "--namespace",
            "myns",
            "--url",
            "https://example.com/hook",
            "--events",
            "design.published,design.yanked",
        ],
    )
    assert result.exit_code == 0
    assert "https://example.com/hook" in result.output
    assert "design.published" in result.output
    assert "whsec_abcdef1234567890" in result.output
    assert "shown only once" in result.output


def test_webhook_create_json_output(monkeypatch) -> None:
    """webhook create成功のJSON出力。"""

    def _fake_webhook_create(**_kwargs):
        return _WEBHOOK_CREATE_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--json",
            "webhook",
            "create",
            "--namespace",
            "myns",
            "--url",
            "https://example.com/hook",
            "--events",
            "design.published,design.yanked",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["url"] == "https://example.com/hook"
    assert data["secret"] == "whsec_abcdef1234567890"
    assert data["events"] == ["design.published", "design.yanked"]


def test_webhook_create_https_validation(monkeypatch) -> None:
    """http:// URL → exit code 3。"""
    from fabricgate.sdk.api import SDKError

    def _fake_webhook_create(**_kwargs):
        raise SDKError("Webhook URL must use HTTPS.", code=sdk_api.ExitKind.INVALID)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "webhook",
            "create",
            "--namespace",
            "myns",
            "--url",
            "http://example.com/hook",
            "--events",
            "design.published",
        ],
    )
    assert result.exit_code == 3


def test_webhook_create_auth_error(monkeypatch) -> None:
    """未認証時にexit code 2。"""
    from fabricgate.sdk.api import SDKError

    def _fake_webhook_create(**_kwargs):
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "webhook",
            "create",
            "--namespace",
            "myns",
            "--url",
            "https://example.com/hook",
            "--events",
            "design.published",
        ],
    )
    assert result.exit_code == 2


def test_webhook_create_limit_exceeded(monkeypatch) -> None:
    """WEBHOOK_LIMIT_EXCEEDED → exit code 3。"""
    from fabricgate.sdk.api import SDKError

    def _fake_webhook_create(**_kwargs):
        raise SDKError("Webhook limit exceeded.", code=sdk_api.ExitKind.INVALID)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "webhook",
            "create",
            "--namespace",
            "myns",
            "--url",
            "https://example.com/hook",
            "--events",
            "design.published",
        ],
    )
    assert result.exit_code == 3


def test_webhook_list_text_output(monkeypatch) -> None:
    """webhook list — 2件がテーブル形式で表示される。"""

    def _fake_webhook_list(**_kwargs):
        return _WEBHOOK_LIST_ITEMS

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_list", _fake_webhook_list)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "list", "--namespace", "myns"])
    assert result.exit_code == 0
    assert "https://example.com/hook" in result.output
    assert "https://example.com/hook2" in result.output
    assert "ID" in result.output
    assert "URL" in result.output
    assert "EVENTS" in result.output
    assert "STATUS" in result.output


def test_webhook_list_json_output(monkeypatch) -> None:
    """webhook list — JSON出力。"""

    def _fake_webhook_list(**_kwargs):
        return _WEBHOOK_LIST_ITEMS

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_list", _fake_webhook_list)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "webhook", "list", "--namespace", "myns"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["url"] == "https://example.com/hook"
    assert data[1]["url"] == "https://example.com/hook2"


def test_webhook_list_empty(monkeypatch) -> None:
    """webhookが0件のとき「No webhooks found.」メッセージ。"""

    def _fake_webhook_list(**_kwargs):
        return []

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_list", _fake_webhook_list)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "list", "--namespace", "myns"])
    assert result.exit_code == 0
    assert "No webhooks found." in result.output


def test_webhook_delete_success(monkeypatch) -> None:
    """--forceでwebhook delete成功、exit 0。"""

    def _fake_webhook_delete(*_args, **_kwargs):
        return None

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_delete", _fake_webhook_delete)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "delete", "10", "--namespace", "myns", "--force"])
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_webhook_delete_confirmation_abort(monkeypatch) -> None:
    """確認プロンプトでNを入力するとexit 0でキャンセル。"""

    def _fake_webhook_delete(*_args, **_kwargs):
        raise AssertionError("delete should not be called")

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_delete", _fake_webhook_delete)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "delete", "10", "--namespace", "myns"], input="N\n")
    assert result.exit_code == 0


def test_webhook_test_success(monkeypatch) -> None:
    """テスト配信成功 — ✓とstatus, durationが表示される。"""

    def _fake_webhook_test(*_args, **_kwargs):
        return _WEBHOOK_TEST_SUCCESS

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_test", _fake_webhook_test)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "test", "10", "--namespace", "myns"])
    assert result.exit_code == 0
    assert "\u2713" in result.output
    assert "200" in result.output
    assert "120" in result.output


def test_webhook_test_failure(monkeypatch) -> None:
    """テスト配信失敗 — ✗が表示される。"""

    def _fake_webhook_test(*_args, **_kwargs):
        return _WEBHOOK_TEST_FAILURE

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_test", _fake_webhook_test)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "test", "10", "--namespace", "myns"])
    assert result.exit_code == 0
    assert "\u2717" in result.output
    assert "500" in result.output
    assert "3000" in result.output


def test_webhook_deliveries_output(monkeypatch) -> None:
    """配信ログがテーブル形式で表示される。"""

    def _fake_webhook_deliveries(*_args, **_kwargs):
        return _WEBHOOK_DELIVERIES

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_deliveries", _fake_webhook_deliveries)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "deliveries", "10", "--namespace", "myns"])
    assert result.exit_code == 0
    assert "d-001" in result.output
    assert "d-002" in result.output
    assert "design.published" in result.output
    assert "ID" in result.output
    assert "EVENT" in result.output


def test_webhook_deliveries_with_limit(monkeypatch) -> None:
    """--limitオプションが正しく渡される。"""
    captured_kwargs: dict = {}

    def _fake_webhook_deliveries(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _WEBHOOK_DELIVERIES[:1]

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_deliveries", _fake_webhook_deliveries)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "deliveries", "10", "--namespace", "myns", "--limit", "5"])
    assert result.exit_code == 0
    assert "d-001" in result.output
    assert captured_kwargs["limit"] == 5


# ===========================================================================
# CLI-YANK-001: yank command — single/multi version soft-delete
# ===========================================================================


_YANK_SINGLE = [
    YankResult(name="alice/counter", version="1.0.0", yanked=True, yanked_reason="critical bug"),
]

_YANK_MULTI = [
    YankResult(name="alice/counter", version="0.9.0", yanked=True, yanked_reason="cve-2026-1234"),
    YankResult(name="alice/counter", version="1.0.0", yanked=True, yanked_reason="cve-2026-1234"),
]


def test_yank_single_version_text(monkeypatch) -> None:
    """fabricgate yank ns/design:1.0.0 --reason "bug" → ✓ yanked + reason表示。"""

    def _fake_yank(*_args, **_kwargs):
        return _YANK_SINGLE

    monkeypatch.setattr("fabricgate.cli.commands.yank.sdk_api.yank", _fake_yank)
    runner = CliRunner()
    result = runner.invoke(main, ["yank", "alice/counter:1.0.0", "--reason", "critical bug"])
    assert result.exit_code == 0
    assert "\u2713" in result.output
    assert "alice/counter:1.0.0" in result.output
    assert "Reason: critical bug" in result.output


def test_yank_single_version_json(monkeypatch) -> None:
    """--json出力でYankResultの配列が返る。"""

    def _fake_yank(*_args, **_kwargs):
        return _YANK_SINGLE

    monkeypatch.setattr("fabricgate.cli.commands.yank.sdk_api.yank", _fake_yank)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "yank", "alice/counter:1.0.0", "--reason", "critical bug"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "alice/counter"
    assert data[0]["version"] == "1.0.0"
    assert data[0]["yanked"] is True
    assert data[0]["yanked_reason"] == "critical bug"


def test_yank_multi_version_text(monkeypatch) -> None:
    """fabricgate yank ns/design 0.9.0 1.0.0 --reason "cve" → 2件のyanked表示。"""

    def _fake_yank(*_args, **_kwargs):
        return _YANK_MULTI

    monkeypatch.setattr("fabricgate.cli.commands.yank.sdk_api.yank", _fake_yank)
    runner = CliRunner()
    result = runner.invoke(main, ["yank", "alice/counter", "0.9.0", "1.0.0", "--reason", "cve-2026-1234"])
    assert result.exit_code == 0
    assert "alice/counter:0.9.0" in result.output
    assert "alice/counter:1.0.0" in result.output
    assert "2 versions" in result.output
    assert "Reason: cve-2026-1234" in result.output


def test_yank_auth_error(monkeypatch) -> None:
    """未認証/権限不足でexit code 2。"""
    from fabricgate.sdk.api import SDKError

    def _fake_yank(*_args, **_kwargs):
        raise SDKError("Permission denied", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.yank.sdk_api.yank", _fake_yank)
    runner = CliRunner()
    result = runner.invoke(main, ["yank", "alice/counter:1.0.0", "--reason", "bug"])
    assert result.exit_code == 2


def test_yank_not_found(monkeypatch) -> None:
    """存在しないデザインでexit code 1。"""
    from fabricgate.sdk.api import SDKError

    def _fake_yank(*_args, **_kwargs):
        raise SDKError("[404] NOT_FOUND: Design not found", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.yank.sdk_api.yank", _fake_yank)
    runner = CliRunner()
    result = runner.invoke(main, ["yank", "alice/missing:1.0.0", "--reason", "bug"])
    assert result.exit_code == 1


# ===========================================================================
# CLI-DEPRECATE-001: deprecate command
# ===========================================================================


_DEPRECATE_SINGLE = [
    DeprecateResult(
        name="alice/counter",
        version="1.0.0",
        deprecated=True,
        deprecation_message="Upgrade to 2.0.0",
        successor="alice/counter:2.0.0",
    ),
]

_UNDEPRECATE_SINGLE = [
    DeprecateResult(
        name="alice/counter",
        version="1.0.0",
        deprecated=False,
        deprecation_message=None,
        successor=None,
    ),
]


def test_deprecate_single_version_text(monkeypatch) -> None:
    def _fake_deprecate(*_args, **_kwargs):
        return _DEPRECATE_SINGLE

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.deprecate", _fake_deprecate)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "deprecate",
            "alice/counter:1.0.0",
            "--message",
            "Upgrade to 2.0.0",
            "--successor",
            "alice/counter:2.0.0",
        ],
    )
    assert result.exit_code == 0
    assert "deprecated" in result.output
    assert "Message: Upgrade to 2.0.0" in result.output
    assert "Successor: alice/counter:2.0.0" in result.output


def test_deprecate_json_output(monkeypatch) -> None:
    def _fake_deprecate(*_args, **_kwargs):
        return _DEPRECATE_SINGLE

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.deprecate", _fake_deprecate)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--json",
            "deprecate",
            "alice/counter:1.0.0",
            "--message",
            "Upgrade to 2.0.0",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["deprecated"] is True


def test_undeprecate_text(monkeypatch) -> None:
    def _fake_undeprecate(*_args, **_kwargs):
        return _UNDEPRECATE_SINGLE

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.undeprecate", _fake_undeprecate)
    runner = CliRunner()
    result = runner.invoke(main, ["deprecate", "--undo", "alice/counter:1.0.0"])
    assert result.exit_code == 0
    assert "Undeprecating" in result.output
    assert "undeprecated" in result.output


def test_deprecate_requires_message_unless_undo() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["deprecate", "alice/counter:1.0.0"])
    assert result.exit_code == 2
    assert "--message is required" in result.output


def test_deprecate_exit_codes(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_permission(*_args, **_kwargs):
        raise SDKError("forbidden", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.deprecate", _fake_permission)
    runner = CliRunner()
    result_permission = runner.invoke(
        main,
        ["deprecate", "alice/counter:1.0.0", "--message", "legacy"],
    )
    assert result_permission.exit_code == 2

    def _fake_not_found(*_args, **_kwargs):
        raise SDKError("missing", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.deprecate", _fake_not_found)
    result_not_found = runner.invoke(
        main,
        ["deprecate", "alice/missing:1.0.0", "--message", "legacy"],
    )
    assert result_not_found.exit_code == 1


# ===========================================================================
# CLI-LICENSE-001: license-check command
# ===========================================================================


_LICENSE_TOOL_REQS = [
    LicenseCheckToolReq(tool="vivado", min_version="2023.1", edition="enterprise", required=True, note="Synthesis"),
    LicenseCheckToolReq(tool="vitis", min_version=None, edition=None, required=False, note="Optional HLS"),
]

_LICENSE_INFO_LIST = LicenseCheckInfo(
    design="alice/counter",
    version="1.0.0",
    tool_requirements=_LICENSE_TOOL_REQS,
    check=None,
)

_LICENSE_INFO_CHECK_PASS = LicenseCheckInfo(
    design="alice/counter",
    version="1.0.0",
    tool_requirements=_LICENSE_TOOL_REQS,
    check=LicenseCheckVerdict(
        tool="vivado",
        edition="enterprise",
        meets_requirements=True,
        notes=["Vivado 2023.2 >= 2023.1", "Edition enterprise matches"],
    ),
)

_LICENSE_INFO_CHECK_FAIL = LicenseCheckInfo(
    design="alice/counter",
    version="1.0.0",
    tool_requirements=_LICENSE_TOOL_REQS,
    check=LicenseCheckVerdict(
        tool="vivado",
        edition="standard",
        meets_requirements=False,
        notes=["Edition standard does not match enterprise"],
    ),
)

_LICENSE_INFO_EMPTY = LicenseCheckInfo(
    design="alice/counter",
    version="1.0.0",
    tool_requirements=[],
    check=None,
)


def test_license_check_list_mode(monkeypatch) -> None:
    """license-check リストモード — ツール要件が表示される。"""

    def _fake_license_check(*_args, **_kwargs):
        return _LICENSE_INFO_LIST

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(main, ["license-check", "alice/counter:1.0.0"])
    assert result.exit_code == 0
    assert "vivado" in result.output
    assert "vitis" in result.output
    assert "Tool Requirements:" in result.output
    assert "Disclaimer:" in result.output


def test_license_check_json_mode(monkeypatch) -> None:
    """license-check JSON出力 — 有効なJSONが返される。"""

    def _fake_license_check(*_args, **_kwargs):
        return _LICENSE_INFO_LIST

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "license-check", "alice/counter:1.0.0"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["design"] == "alice/counter"
    assert data["version"] == "1.0.0"
    assert len(data["tool_requirements"]) == 2
    assert data["tool_requirements"][0]["tool"] == "vivado"
    assert data["check"] is None


def test_license_check_with_tool_and_edition(monkeypatch) -> None:
    """--tool/--edition指定でチェックモード、要件を満たす場合exit 0。"""

    def _fake_license_check(*_args, **_kwargs):
        return _LICENSE_INFO_CHECK_PASS

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["license-check", "alice/counter:1.0.0", "--tool", "vivado", "--edition", "enterprise"],
    )
    assert result.exit_code == 0
    assert "MEETS REQUIREMENTS" in result.output
    assert "\u2713" in result.output


def test_license_check_does_not_meet(monkeypatch) -> None:
    """要件を満たさない場合exit 3。"""

    def _fake_license_check(*_args, **_kwargs):
        return _LICENSE_INFO_CHECK_FAIL

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(main, ["license-check", "alice/counter:1.0.0", "--tool", "vivado", "--edition", "standard"])
    assert result.exit_code == 3
    assert "DOES NOT MEET REQUIREMENTS" in result.output
    assert "\u2717" in result.output


def test_license_check_empty_requirements(monkeypatch) -> None:
    """tool_requirements が空の場合 exit 1: GENERIC。ADR-008 で PERMISSION=2 との衝突を回避。"""

    def _fake_license_check(*_args, **_kwargs):
        return _LICENSE_INFO_EMPTY

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(main, ["license-check", "alice/counter:1.0.0"])
    assert result.exit_code == 1
    assert "No tool requirements defined." in result.output


def test_license_check_error(monkeypatch) -> None:
    """SDKError時にexit code 1。"""
    from fabricgate.sdk.api import SDKError

    def _fake_license_check(*_args, **_kwargs):
        raise SDKError("[404] NOT_FOUND: Design not found", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.license_check.sdk_api.license_check", _fake_license_check)
    runner = CliRunner()
    result = runner.invoke(main, ["license-check", "alice/counter:1.0.0"])
    assert result.exit_code == 1


# ===========================================================================
# CLI-DIFF-001: diff command
# ===========================================================================


_DIFF_RESULT = VersionDiffResponse(
    base="1.0.0",
    head="2.0.0",
    summary=VersionDiffSummary(
        platforms_added=["xczu7ev/nanopynq"],
        platforms_removed=[],
        platforms_changed=["xczu7ev/pynq"],
    ),
    diff=[
        VersionDiffPlatform(
            platform="xczu7ev/pynq",
            fields=[
                VersionDiffField(field="bitstream_type", base=None, head="partial"),
                VersionDiffField(field="artifacts[0].sha256", base="aabb", head="cafe"),
                VersionDiffField(field="artifacts[0].size", base=262144, head=524288),
                VersionDiffField(
                    field="tool_requirements",
                    base=[],
                    head=[{"tool": "vivado", "min_version": "2024.1"}],
                ),
            ],
        ),
        VersionDiffPlatform(platform="xczu7ev/nanopynq", fields="added"),
    ],
)


def test_diff_text_output(monkeypatch) -> None:
    def _fake_diff(*_args, **_kwargs):
        return _DIFF_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])

    assert result.exit_code == 0
    assert "Diff: alice/counter  1.0.0 → 2.0.0" in result.output
    assert "Platforms added:   xczu7ev/nanopynq" in result.output
    assert "Platforms changed: xczu7ev/pynq" in result.output
    assert 'bitstream_type      null → "partial"' in result.output
    assert "artifacts[0].size   256 KB → 512 KB" in result.output
    assert "(added in 2.0.0)" in result.output


def test_diff_json_output(monkeypatch) -> None:
    def _fake_diff(*_args, **_kwargs):
        return _DIFF_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "diff", "alice/counter:2.0.0", "--base", "1.0.0"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["base"] == "1.0.0"
    assert data["head"] == "2.0.0"
    assert data["summary"]["platforms_changed"] == ["xczu7ev/pynq"]


def test_diff_no_changes(monkeypatch) -> None:
    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="1.0.0+build.2",
            summary=VersionDiffSummary(),
            diff=[],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:1.0.0+build.2", "--base", "1.0.0"])

    assert result.exit_code == 0
    assert "Platforms added:   (none)" in result.output
    assert "No differences found." in result.output


def test_diff_platform_filter(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}

    def _fake_diff(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _DIFF_RESULT

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", "alice/counter:2.0.0", "--base", "1.0.0", "--platform", "xczu7ev/pynq"],
    )

    assert result.exit_code == 0
    assert captured_kwargs["platform"] == "xczu7ev/pynq"


def test_diff_not_found_exit_1(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_diff(*_args, **_kwargs):
        raise SDKError("[404] NOT_FOUND: Design not found", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/missing:2.0.0", "--base", "1.0.0"])

    assert result.exit_code == 1


def test_diff_network_error_exit_4(monkeypatch) -> None:
    from fabricgate.sdk.api import SDKError

    def _fake_diff(*_args, **_kwargs):
        raise SDKError("Network error: Connection refused", code=sdk_api.ExitKind.INFRA)

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])

    assert result.exit_code == 4


def test_diff_text_sanitizes_control_characters(monkeypatch) -> None:
    poisoned = VersionDiffResponse.model_construct(
        base="1.0.0",
        head="2.0.0",
        summary=VersionDiffSummary.model_construct(
            platforms_added=[],
            platforms_removed=[],
            platforms_changed=["xczu7ev/pynq\n\x1b[31m"],
        ),
        diff=[
            VersionDiffPlatform.model_construct(
                platform="xczu7ev/pynq\n\x1b[31m",
                fields=[VersionDiffField(field="bad\nfield", base="a", head="b")],
            )
        ],
    )

    def _fake_diff(*_args, **_kwargs):
        return poisoned

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])

    assert result.exit_code == 0
    assert "\x1b" not in result.output
    assert "bad\nfield" not in result.output


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


def test_watch_sdk_error(monkeypatch) -> None:
    def _raise(*_args, **_kwargs) -> None:
        raise sdk_api.SDKError("network failure", code=sdk_api.ExitKind.INFRA)

    monkeypatch.setattr("fabricgate.cli.commands.watch.sdk_api.watch", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["watch", "ns/blink:1.0.0"])
    assert result.exit_code == 4
    assert "network failure" in result.output


def test_watch_json_new_version_found(monkeypatch) -> None:
    def _fake_watch(*_args, **_kwargs):
        return WatchResult(
            design_name="ns/blink",
            new_version_found=True,
            latest_version="2.0.0",
            new_versions=["2.0.0"],
            platforms=["xc7z020/pynq"],
        )

    monkeypatch.setattr("fabricgate.cli.commands.watch.sdk_api.watch", _fake_watch)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "watch", "ns/blink:1.0.0"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["new_version_found"] is True
    assert data["latest_version"] == "2.0.0"


def test_watch_json_no_new_version(monkeypatch) -> None:
    def _fake_watch(*_args, **_kwargs):
        return WatchResult(
            design_name="ns/blink",
            new_version_found=False,
            latest_version="1.0.0",
        )

    monkeypatch.setattr("fabricgate.cli.commands.watch.sdk_api.watch", _fake_watch)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "watch", "ns/blink:1.0.0"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["new_version_found"] is False


def test_watch_text_new_version_found(monkeypatch) -> None:
    def _fake_watch(*_args, **_kwargs):
        return WatchResult(
            design_name="ns/blink",
            new_version_found=True,
            latest_version="2.0.0",
            new_versions=["2.0.0"],
            platforms=["xc7z020/pynq"],
        )

    monkeypatch.setattr("fabricgate.cli.commands.watch.sdk_api.watch", _fake_watch)
    runner = CliRunner()
    result = runner.invoke(main, ["watch", "ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "New version found" in result.output
    assert "ns/blink" in result.output
    assert "2.0.0" in result.output
    assert "xc7z020/pynq" in result.output


def test_watch_text_no_new_version(monkeypatch) -> None:
    def _fake_watch(*_args, **_kwargs):
        return WatchResult(
            design_name="ns/blink",
            new_version_found=False,
            latest_version="1.0.0",
        )

    monkeypatch.setattr("fabricgate.cli.commands.watch.sdk_api.watch", _fake_watch)
    runner = CliRunner()
    result = runner.invoke(main, ["watch", "ns/blink:1.0.0"])
    assert result.exit_code == 1
    assert "No new version found" in result.output
    assert "ns/blink" in result.output
    assert "1.0.0" in result.output


# ---------------------------------------------------------------------------
# info (additional paths)
# ---------------------------------------------------------------------------


def test_info_sdk_error(monkeypatch) -> None:
    def _raise(*_args, **_kwargs) -> None:
        raise sdk_api.SDKError("not found", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.info.sdk_api.info", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["info", "ns/blink:1.0.0"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_info_json_output(monkeypatch) -> None:
    def _fake_info(*_args, **_kwargs):
        return DesignInfo(
            name="ns/blink",
            version="1.0.0",
            platforms=[
                PlatformEntry(
                    platform="xc7z020/pynq",
                    digest="sha256:" + "aa" * 32,
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.info.sdk_api.info", _fake_info)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "info", "ns/blink:1.0.0"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "ns/blink"
    assert data["version"] == "1.0.0"


def test_info_all_optional_fields(monkeypatch) -> None:
    def _fake_info(*_args, **_kwargs):
        return DesignInfo(
            name="ns/blink",
            version="1.0.0",
            license="MIT",
            author="Alice",
            repository="https://github.com/alice/blink",
            tags=["fpga", "zynq"],
            platforms=[
                PlatformEntry(
                    platform="xc7z020/pynq",
                    digest="sha256:" + "aa" * 32,
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.info.sdk_api.info", _fake_info)
    runner = CliRunner()
    result = runner.invoke(main, ["info", "ns/blink:1.0.0"])
    assert result.exit_code == 0
    assert "License: MIT" in result.output
    assert "Author: Alice" in result.output
    assert "Repository: https://github.com/alice/blink" in result.output
    assert "Tags: fpga, zynq" in result.output


# ---------------------------------------------------------------------------
# verify (additional paths)
# ---------------------------------------------------------------------------


def test_verify_sdk_error(monkeypatch, tmp_path) -> None:
    def _raise(*_args, **_kwargs) -> None:
        raise sdk_api.SDKError("corrupt manifest", code=sdk_api.ExitKind.INVALID)

    monkeypatch.setattr("fabricgate.cli.commands.verify.sdk_api.verify", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(tmp_path)])
    assert result.exit_code == 3
    assert "corrupt manifest" in result.output


def test_verify_json_output(monkeypatch, tmp_path) -> None:
    def _fake_verify(*_args, **_kwargs):
        return VerificationResult(
            design_ref="ns/blink:1.0.0",
            platform="xc7z020/pynq",
            directory=str(tmp_path),
            artifacts=[VerificationItem(file="design.bit", sha256="abc123", verified=True)],
        )

    monkeypatch.setattr("fabricgate.cli.commands.verify.sdk_api.verify", _fake_verify)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "verify", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["design_ref"] == "ns/blink:1.0.0"
    assert data["artifacts"][0]["verified"] is True


def test_verify_success(monkeypatch, tmp_path) -> None:
    def _fake_verify(*_args, **_kwargs):
        return VerificationResult(
            design_ref="ns/blink:1.0.0",
            platform="xc7z020/pynq",
            directory=str(tmp_path),
            artifacts=[VerificationItem(file="design.bit", sha256="abc123", verified=True)],
        )

    monkeypatch.setattr("fabricgate.cli.commands.verify.sdk_api.verify", _fake_verify)
    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(tmp_path)])
    assert result.exit_code == 0
    assert "All artifacts verified." in result.output


# ---------------------------------------------------------------------------
# deprecate (additional paths) — lines 32, 34, 66
# ---------------------------------------------------------------------------


def test_deprecate_undo_with_message_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["deprecate", "--undo", "--message", "upgrade", "alice/counter:1.0.0"])
    assert result.exit_code == 2
    assert "--message cannot be used with --undo" in result.output


def test_deprecate_undo_with_successor_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["deprecate", "--undo", "--successor", "alice/counter:2.0.0", "alice/counter:1.0.0"])
    assert result.exit_code == 2
    assert "--successor cannot be used with --undo" in result.output


def test_deprecate_multiple_versions_text(monkeypatch) -> None:
    """count > 1 → 'N versions of ...' branch (line 66)."""

    def _fake_deprecate(*_args, **_kwargs):
        return [
            DeprecateResult(
                name="alice/counter",
                version="1.0.0",
                deprecated=True,
                deprecation_message="Old",
                successor=None,
            ),
            DeprecateResult(
                name="alice/counter",
                version="1.1.0",
                deprecated=True,
                deprecation_message="Old",
                successor=None,
            ),
        ]

    monkeypatch.setattr("fabricgate.cli.commands.deprecate.sdk_api.deprecate", _fake_deprecate)
    runner = CliRunner()
    result = runner.invoke(main, ["deprecate", "alice/counter", "1.0.0", "1.1.0", "--message", "Old"])
    assert result.exit_code == 0
    assert "2 versions of alice/counter" in result.output


# ---------------------------------------------------------------------------
# login (additional paths) — lines 21-24 (_on_user_code callback body)
# ---------------------------------------------------------------------------


def test_login_triggers_user_code_callback(monkeypatch) -> None:
    def _fake_login(registry: str, on_user_code, **_kwargs):
        on_user_code("https://login.example.com/activate", "ABCD-1234")
        return LoginResult(registry=registry, storage="file (~/.fabricgate)")

    monkeypatch.setattr("fabricgate.cli.commands.login.sdk_api.login", _fake_login)
    runner = CliRunner()
    result = runner.invoke(main, ["login"])
    assert result.exit_code == 0
    assert "https://login.example.com/activate" in result.output
    assert "ABCD-1234" in result.output
    assert "Waiting for authorization" in result.output


# ---------------------------------------------------------------------------
# pull (additional paths) — lines 66-67 (json output)
# ---------------------------------------------------------------------------


def test_pull_json_output(monkeypatch) -> None:
    def _fake_pull(*_args, **_kwargs):
        return PullResult(
            name="ns/blink",
            version="1.0.0",
            platform="xc7z020/pynq",
            path="/tmp/blink",
            artifacts=["design.bit"],
            cached=False,
        )

    monkeypatch.setattr("fabricgate.cli.commands.pull.sdk_api.pull", _fake_pull)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "pull", "ns/blink:1.0.0"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "ns/blink"
    assert data["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# token (additional paths) — lines 63-65 (empty list), 103 (revoke declined)
# ---------------------------------------------------------------------------


def test_token_revoke_declined(monkeypatch) -> None:
    revoked = False

    def _fake_revoke(*_args, **_kwargs):
        nonlocal revoked
        revoked = True

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", _fake_revoke)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "revoke", "42"], input="n\n")
    assert result.exit_code == 0
    assert revoked is False


# ---------------------------------------------------------------------------
# stats (additional paths) — lines 16, 64-65, 72, 87
# ---------------------------------------------------------------------------


def test_stats_namespace_no_top_designs(monkeypatch) -> None:
    """NamespaceStatsInfo with empty top_designs → '(no data)' branch (line 72)."""

    def _fake_stats(**_kwargs):
        return NamespaceStatsInfo(
            namespace="alice",
            total_downloads=0,
            top_designs=[],
            last_7d=0,
            last_30d=0,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "--namespace", "alice"])
    assert result.exit_code == 0
    assert "(no data)" in result.output


def test_stats_design_empty_series(monkeypatch) -> None:
    """DesignStatsInfo with empty series → covers lines 64-65, 87 ('(no data)')."""

    def _fake_stats(**_kwargs):
        return DesignStatsInfo(
            name="alice/counter",
            version=None,
            total_downloads=0,
            period="daily",
            series=[],
            last_7d=0,
            last_30d=0,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "alice/counter"])
    assert result.exit_code == 0
    assert "(no data)" in result.output


def test_stats_design_series_with_zero_downloads(monkeypatch) -> None:
    """Series point with downloads=0 triggers _render_ascii_bar early return (line 16)."""

    def _fake_stats(**_kwargs):
        return DesignStatsInfo(
            name="alice/counter",
            version=None,
            total_downloads=50,
            period="daily",
            series=[
                StatsSeriesItem(date="2026-04-01", downloads=0),
                StatsSeriesItem(date="2026-04-02", downloads=50),
            ],
            last_7d=50,
            last_30d=50,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "alice/counter"])
    assert result.exit_code == 0
    assert "2026-04-01" in result.output
    assert "2026-04-02" in result.output


# ---------------------------------------------------------------------------
# token (additional SDKError paths) — lines 63-65, 103
# ---------------------------------------------------------------------------


def test_token_list_sdk_error(monkeypatch) -> None:
    def _raise(**_kwargs) -> None:
        raise sdk_api.SDKError("unauthorized", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_list", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "list"])
    assert result.exit_code == 2
    assert "unauthorized" in result.output


def test_token_revoke_sdk_error(monkeypatch) -> None:
    def _raise(*_args, **_kwargs) -> None:
        raise sdk_api.SDKError("forbidden", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", _raise)
    runner = CliRunner()
    result = runner.invoke(main, ["token", "revoke", "--force", "42"])
    assert result.exit_code == 2
    assert "forbidden" in result.output


def test_token_revoke_json_output(monkeypatch) -> None:
    monkeypatch.setattr("fabricgate.cli.commands.token.sdk_api.token_revoke", lambda *_a, **_kw: None)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "token", "revoke", "--force", "42"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["revoked"] is True
    assert data["id"] == 42


# ---------------------------------------------------------------------------
# stats (json output path) — lines 64-65
# ---------------------------------------------------------------------------


def test_stats_json_output(monkeypatch) -> None:
    def _fake_stats(**_kwargs):
        return DesignStatsInfo(
            name="alice/counter",
            version=None,
            total_downloads=100,
            period="daily",
            series=[StatsSeriesItem(date="2026-04-01", downloads=100)],
            last_7d=100,
            last_30d=100,
        )

    monkeypatch.setattr("fabricgate.cli.commands.stats.sdk_api.stats", _fake_stats)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "stats", "alice/counter"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "alice/counter"
    assert data["total_downloads"] == 100


# ---------------------------------------------------------------------------
# diff — _format_size / _format_value edge cases + removed platform
# ---------------------------------------------------------------------------


def test_diff_format_size_bytes(monkeypatch) -> None:
    """artifacts[0].size < 1024 → '512 B' (integer bytes path, line 29)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="artifacts[0].size", base=512, head=800)],
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "512 B" in result.output
    assert "800 B" in result.output


def test_diff_format_size_fractional_kb(monkeypatch) -> None:
    """artifacts[0].size = 1536 bytes → '1.5 KB' (non-integer float path, line 32)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="artifacts[0].size", base=1536, head=2560)],
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "1.5 KB" in result.output
    assert "2.5 KB" in result.output


def test_diff_format_value_bool(monkeypatch) -> None:
    """bool values → 'false → true' (line 41 in _format_value)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="verified", base=False, head=True)],
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "false → true" in result.output


def test_diff_format_value_non_size_int(monkeypatch) -> None:
    """int field not ending in 'size' → str(value) (line 45 in _format_value)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="pin_count", base=4, head=8)],
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "4 → 8" in result.output


def test_diff_format_value_float(monkeypatch) -> None:
    """float value → str(value) (line 47 in _format_value)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(),
            diff=[
                VersionDiffPlatform(
                    platform="xczu7ev/pynq",
                    fields=[VersionDiffField(field="clock_freq", base=100.5, head=200.75)],
                )
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "100.5" in result.output
    assert "200.75" in result.output


def test_diff_removed_platform(monkeypatch) -> None:
    """fields='removed' → '(removed from <base>)' (lines 86-87 in _render_text)。"""

    def _fake_diff(*_args, **_kwargs):
        return VersionDiffResponse(
            base="1.0.0",
            head="2.0.0",
            summary=VersionDiffSummary(platforms_removed=["xczu7ev/pynq"]),
            diff=[
                VersionDiffPlatform(platform="xczu7ev/pynq", fields="removed"),
            ],
        )

    monkeypatch.setattr("fabricgate.cli.commands.diff.sdk_api.diff", _fake_diff)
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "alice/counter:2.0.0", "--base", "1.0.0"])
    assert result.exit_code == 0
    assert "(removed from 1.0.0)" in result.output


# ---------------------------------------------------------------------------
# quota — fractional size (_format_bytes line 23)
# ---------------------------------------------------------------------------


def test_quota_bytes_size(monkeypatch) -> None:
    """used_bytes < 1024 → '512 B' (unit == "B" path, line 23 in _format_bytes)。"""

    def _fake_quota(**_kwargs):
        return QuotaResponse(
            namespace="alice",
            storage=QuotaStorageInfo(used_bytes=512, limit_bytes=1023, used_percent=50.1),
            versions_per_design=QuotaVersionsInfo(limit=100),
            designs=QuotaDesignsInfo(used=1, limit=200),
            file_size_limit_bytes=524_288_000,
        )

    monkeypatch.setattr("fabricgate.cli.commands.quota.sdk_api.quota", _fake_quota)
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "--namespace", "alice"])
    assert result.exit_code == 0
    assert "512 B" in result.output


# ---------------------------------------------------------------------------
# webhook CLI — missing coverage paths
# ---------------------------------------------------------------------------


def test_webhook_create_with_design_text(monkeypatch) -> None:
    """webhook create テキスト出力で optional design フィールドが表示される (line 52)。"""

    def _fake_webhook_create(**_kwargs):
        return WebhookCreateResult(
            id=10,
            url="https://example.com/hook",
            events=["design.published"],
            design="alice/blink",
            secret="whsec_abcdef1234567890",
            status="active",
            created_at=datetime(2026, 3, 29, tzinfo=UTC),
        )

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_create", _fake_webhook_create)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "webhook",
            "create",
            "--namespace",
            "alice",
            "--url",
            "https://example.com/hook",
            "--events",
            "design.published",
        ],
    )
    assert result.exit_code == 0
    assert "alice/blink" in result.output


def test_webhook_list_sdk_error_cli(monkeypatch) -> None:
    """webhook list SDKError → exit code 2 (lines 69-71)。"""

    def _fake_webhook_list(**_kwargs):
        raise sdk_api.SDKError("Not authenticated.", code=sdk_api.ExitKind.PERMISSION)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_list", _fake_webhook_list)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "list", "--namespace", "alice"])
    assert result.exit_code == 2


def test_webhook_delete_sdk_error_cli(monkeypatch) -> None:
    """webhook delete SDKError → exit code 1 (lines 104-106)。"""

    def _fake_webhook_delete(*_args, **_kwargs):
        raise sdk_api.SDKError("Not found.", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_delete", _fake_webhook_delete)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "delete", "99", "--namespace", "alice", "--force"])
    assert result.exit_code == 1


def test_webhook_delete_json_output_cli(monkeypatch) -> None:
    """webhook delete --json → {"deleted": true, "id": N} (line 109)。"""

    def _fake_webhook_delete(*_args, **_kwargs):
        return None

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_delete", _fake_webhook_delete)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "webhook", "delete", "10", "--namespace", "alice"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["deleted"] is True
    assert data["id"] == 10


def test_webhook_test_sdk_error_cli(monkeypatch) -> None:
    """webhook test SDKError → exit code 1 (lines 127-129)。"""

    def _fake_webhook_test(*_args, **_kwargs):
        raise sdk_api.SDKError("Webhook not found.", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_test", _fake_webhook_test)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "test", "99", "--namespace", "alice"])
    assert result.exit_code == 1


def test_webhook_test_json_output_cli(monkeypatch) -> None:
    """webhook test --json → JSON出力 (line 132)。"""

    def _fake_webhook_test(*_args, **_kwargs):
        return WebhookTestResult(delivered=True, status_code=200, duration_ms=50)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_test", _fake_webhook_test)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "webhook", "test", "10", "--namespace", "alice"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["delivered"] is True
    assert data["status_code"] == 200


def test_webhook_deliveries_sdk_error_cli(monkeypatch) -> None:
    """webhook deliveries SDKError → exit code 1 (lines 153-155)。"""

    def _fake_webhook_deliveries(*_args, **_kwargs):
        raise sdk_api.SDKError("Webhook not found.", code=sdk_api.ExitKind.NOT_FOUND)

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_deliveries", _fake_webhook_deliveries)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "deliveries", "99", "--namespace", "alice"])
    assert result.exit_code == 1


def test_webhook_deliveries_json_output_cli(monkeypatch) -> None:
    """webhook deliveries --json → JSON配列出力 (line 158)。"""

    def _fake_webhook_deliveries(*_args, **_kwargs):
        return _WEBHOOK_DELIVERIES

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_deliveries", _fake_webhook_deliveries)
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "webhook", "deliveries", "10", "--namespace", "alice"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["id"] == "d-001"


def test_webhook_deliveries_empty_cli(monkeypatch) -> None:
    """webhook deliveries 0件 → 'No deliveries found.' (lines 161-162)。"""

    def _fake_webhook_deliveries(*_args, **_kwargs):
        return []

    monkeypatch.setattr("fabricgate.cli.commands.webhook.sdk_api.webhook_deliveries", _fake_webhook_deliveries)
    runner = CliRunner()
    result = runner.invoke(main, ["webhook", "deliveries", "10", "--namespace", "alice"])
    assert result.exit_code == 0
    assert "No deliveries found." in result.output


def test_exit_code_table_covers_every_failure_kind() -> None:
    from fabricgate.cli.exit_codes import EXIT_CODE
    from fabricgate.client.errors import FailureKind

    # Every semantic kind must have an exit code (no KeyError fallthrough).
    assert set(EXIT_CODE) == set(FailureKind)
    assert EXIT_CODE[FailureKind.PERMISSION] == 2
    assert EXIT_CODE[FailureKind.UNRESOLVABLE] == 5
    assert EXIT_CODE[FailureKind.SHELL_NOT_FOUND] == 6


class TestUnsupportedCommandsAreHidden:
    """token / webhook call registry endpoints that do not exist yet (issue #6).

    They stay importable so the implementation is not lost, but they must not
    appear in `--help`, where they would advertise a surface that 404s.
    """

    def test_hidden_from_help(self):
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0, result.output
        assert "token" not in result.output
        assert "webhook" not in result.output

    def test_still_registered(self):
        from fabricgate.cli.commands.token import token_group
        from fabricgate.cli.commands.webhook import webhook_group

        assert token_group.hidden is True
        assert webhook_group.hidden is True
        assert {"token", "webhook"} <= set(main.commands)
