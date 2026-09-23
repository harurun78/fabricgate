"""Unit tests for fabricgate.client sub-modules."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from fabricgate.client import cache, config, resolver, validator
from fabricgate.client.auth import (
    delete_credentials,
    load_credentials,
    save_credentials,
)
from fabricgate.client.publisher import (
    PublishError,
    collect_artifacts,
    load_design_index,
)
from fabricgate.models.cli import CacheIndex, Credentials, RegistryConfig
from fabricgate.models.design_index import DesignIndex, PlatformEntry

_FAKE_DIGEST = "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd"


# ============================================================================
# config
# ============================================================================


class TestConfig:
    def test_load_config_defaults(self, tmp_path: Path) -> None:
        cfg = config.load_config(tmp_path / "non-existent.yaml")
        assert cfg.registry == "https://registry.fabricgate.dev/api/v1"
        assert cfg.platform is None

    def test_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yaml"
        cfg = RegistryConfig(
            registry="https://example.com/api/v1",
            platform="xc7z020/pynq",
            cache_dir="~/.fabricgate/cache",
        )
        config.save_config(cfg, p)
        loaded = config.load_config(p)
        assert loaded.registry == cfg.registry
        assert loaded.platform == cfg.platform

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "dir" / "cfg.yaml"
        config.save_config(RegistryConfig(), p)
        assert p.exists()

    def test_env_overrides_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "cfg.yaml"
        config.save_config(RegistryConfig(registry="https://file.example/api/v1"), p)
        monkeypatch.setenv("FG_REGISTRY", "https://env.example/api/v1")
        loaded = config.load_config(p)
        assert loaded.registry == "https://env.example/api/v1"

    def test_env_overrides_platform(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "cfg.yaml"
        config.save_config(RegistryConfig(), p)
        monkeypatch.setenv("FG_PLATFORM", "xc7z020/pynq")
        loaded = config.load_config(p)
        assert loaded.platform == "xc7z020/pynq"

    def test_env_overrides_cache_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "cfg.yaml"
        config.save_config(RegistryConfig(), p)
        monkeypatch.setenv("FG_CACHE_DIR", "/tmp/my-cache")
        loaded = config.load_config(p)
        assert loaded.cache_dir == "/tmp/my-cache"


@pytest.fixture()
def file_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force file-backed credential storage for tests that assert file behavior."""
    import fabricgate.client.auth as auth_module

    monkeypatch.setattr(auth_module, "_try_keyring_load", lambda _registry: None)
    monkeypatch.setattr(auth_module, "_try_keyring_save", lambda _cred: False)
    monkeypatch.setattr(auth_module, "_try_keyring_delete", lambda _registry: False)


# ============================================================================
# auth (file-based fallback only — keyring is optional)
# ============================================================================


class TestAuth:
    def _cred(self, registry: str = "https://r.example.com") -> Credentials:
        return Credentials(
            registry=registry,
            token="tok-abc",
            expires_at=datetime(2025, 12, 31, tzinfo=UTC),
            scopes=["read", "write"],
        )

    def test_save_and_load(self, tmp_path: Path, file_credentials: None) -> None:
        p = tmp_path / "creds.json"
        cred = self._cred()
        save_credentials(cred, p)
        loaded = load_credentials("https://r.example.com", p)
        assert loaded is not None
        assert loaded.token == "tok-abc"

    def test_delete(self, tmp_path: Path, file_credentials: None) -> None:
        p = tmp_path / "creds.json"
        save_credentials(self._cred(), p)
        delete_credentials("https://r.example.com", p)
        assert load_credentials("https://r.example.com", p) is None

    def test_load_missing(self, tmp_path: Path, file_credentials: None) -> None:
        assert load_credentials("x", tmp_path / "no.json") is None

    def test_file_permissions(self, tmp_path: Path, file_credentials: None) -> None:
        p = tmp_path / "creds.json"
        save_credentials(self._cred(), p)
        # 0600 = owner-only read/write
        assert p.stat().st_mode & 0o777 == 0o600

    def test_multiple_registries(self, tmp_path: Path, file_credentials: None) -> None:
        p = tmp_path / "creds.json"
        save_credentials(self._cred("https://a.example.com"), p)
        save_credentials(self._cred("https://b.example.com"), p)
        assert load_credentials("https://a.example.com", p) is not None
        assert load_credentials("https://b.example.com", p) is not None

    def test_keyring_load_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """keyring.get_password が認証情報を返すとき、ファイルを読まずに返す。"""
        cred = self._cred()

        import keyring as _keyring_module

        monkeypatch.setattr(_keyring_module, "get_password", lambda _svc, _reg: cred.model_dump_json())
        loaded = load_credentials("https://r.example.com")
        assert loaded is not None
        assert loaded.token == "tok-abc"

    def test_keyring_save_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """keyring.set_password が成功するとき True を返す (ファイル書き込みなし)。"""
        saved: list[str] = []

        import keyring as _keyring_module

        monkeypatch.setattr(_keyring_module, "set_password", lambda _svc, _reg, _val: saved.append(_val))
        cred = self._cred()
        save_credentials(cred)
        assert len(saved) == 1

    def test_keyring_delete_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """keyring.delete_password が成功するとき True を返す (ファイル読み込みなし)。"""
        deleted: list[str] = []

        import keyring as _keyring_module

        monkeypatch.setattr(_keyring_module, "delete_password", lambda _svc, _reg: deleted.append(_reg))
        delete_credentials("https://r.example.com")
        assert len(deleted) == 1


# ============================================================================
# validator
# ============================================================================


class TestValidator:
    def test_sha256_hex(self, tmp_path: Path) -> None:
        p = tmp_path / "blob"
        p.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert validator.sha256_hex(p) == expected

    def test_sha256_digest(self, tmp_path: Path) -> None:
        p = tmp_path / "blob"
        p.write_bytes(b"data")
        expected = f"sha256:{hashlib.sha256(b'data').hexdigest()}"
        assert validator.sha256_digest(p) == expected

    def test_verify_artifact(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        p.write_bytes(b"test")
        h = hashlib.sha256(b"test").hexdigest()
        assert validator.verify_artifact(p, h) is True
        assert validator.verify_artifact(p, "0" * 64) is False

    def test_verify_digest(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        p.write_bytes(b"test")
        d = f"sha256:{hashlib.sha256(b'test').hexdigest()}"
        assert validator.verify_digest(p, d) is True
        assert validator.verify_digest(p, "sha256:bad") is False


# ============================================================================
# resolver
# ============================================================================


class TestResolver:
    def _index(self, platforms: list[PlatformEntry]) -> DesignIndex:
        return DesignIndex.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": "test-ns/blink",
                "version": "1.0.0",
                "summary": "test",
                "platforms": [{"platform": e.platform, "digest": e.digest} for e in platforms],
            }
        )

    def _entry(self, platform: str = "xc7z020/pynq") -> PlatformEntry:
        return PlatformEntry.model_validate(
            {
                "platform": platform,
                "digest": _FAKE_DIGEST,
            }
        )

    def test_single_platform_auto_select(self) -> None:
        idx = self._index([self._entry()])
        result = resolver.resolve_platform(idx)
        assert result.platform == "xc7z020/pynq"

    def test_explicit_match(self) -> None:
        idx = self._index([self._entry(), self._entry("xczu3eg/linux-fpgamgr")])
        result = resolver.resolve_platform(idx, "xczu3eg/linux-fpgamgr")
        assert result.platform == "xczu3eg/linux-fpgamgr"

    def test_multiple_without_flag(self) -> None:
        idx = self._index([self._entry(), self._entry("xczu3eg/linux-fpgamgr")])
        with pytest.raises(resolver.ResolutionError, match="specify --platform"):
            resolver.resolve_platform(idx)

    def test_no_match(self) -> None:
        idx = self._index([self._entry()])
        with pytest.raises(resolver.ResolutionError, match="not found"):
            resolver.resolve_platform(idx, "nonexistent/platform")


class TestFamilyFallbackResolution:
    """Two-stage resolution: exact match first, then generic-{family} fallback.

    Spec: docs/specs/client-behavior.md §6
    (pynq-z2 / generic-xc7z020 exist in the bundled official board-db).
    """

    def _index_with(self, *platforms: str) -> DesignIndex:
        return DesignIndex.model_validate(
            {
                "schema": "fabricgate-index/v1",
                "name": "test-ns/blink",
                "version": "1.0.0",
                "summary": "test",
                "platforms": [{"platform": p, "digest": _FAKE_DIGEST} for p in platforms],
            }
        )

    def test_exact_match_takes_priority_over_generic(self) -> None:
        idx = self._index_with("pynq-z2/pynq", "generic-xc7z020/pynq")
        res = resolver.resolve_platform_detailed(idx, "pynq-z2/pynq")
        assert res.entry.platform == "pynq-z2/pynq"
        assert res.fallback_from is None

    def test_family_fallback_on_miss(self) -> None:
        idx = self._index_with("generic-xc7z020/pynq")
        res = resolver.resolve_platform_detailed(idx, "pynq-z2/pynq")  # pynq-z2 is xc7z020 family
        assert res.entry.platform == "generic-xc7z020/pynq"
        assert res.fallback_from == "pynq-z2/pynq"

    def test_unknown_board_no_fallback(self) -> None:
        idx = self._index_with("generic-xc7z020/pynq")
        with pytest.raises(resolver.ResolutionError, match="not found"):
            resolver.resolve_platform_detailed(idx, "no-such-board/pynq")

    def test_fallback_target_absent_raises(self) -> None:
        idx = self._index_with("generic-xczu7ev/pynq")
        with pytest.raises(resolver.ResolutionError, match="not found"):
            resolver.resolve_platform_detailed(idx, "pynq-z2/pynq")  # no generic-xc7z020 entry

    @pytest.mark.parametrize(
        ("board_id", "generic"),
        [
            ("pynq-z1", "generic-xc7z020"),
            ("zcu111", "generic-xczu28dr"),
            ("rfsoc2x2", "generic-xczu28dr"),
            ("rfsoc4x2", "generic-xczu48dr"),
        ],
    )
    def test_pynq_curation_boards_are_known(self, board_id: str, generic: str) -> None:
        """Boards added for the PYNQ overlay index resolve exactly and via family fallback
        instead of failing as an unregistered board."""
        exact = f"{board_id}/pynq"
        idx = self._index_with(exact, f"{generic}/pynq")
        assert resolver.resolve_platform_detailed(idx, exact).fallback_from is None
        res = resolver.resolve_platform_detailed(self._index_with(f"{generic}/pynq"), exact)
        assert res.entry.platform == f"{generic}/pynq"
        assert res.fallback_from == exact

    def test_runtime_is_preserved_in_fallback(self) -> None:
        idx = self._index_with("generic-xc7z020/pynq", "generic-xc7z020/linux-fpgamgr")
        res = resolver.resolve_platform_detailed(idx, "pynq-z2/linux-fpgamgr")
        assert res.entry.platform == "generic-xc7z020/linux-fpgamgr"
        assert res.fallback_from == "pynq-z2/linux-fpgamgr"

    def test_resolve_platform_delegates_to_detailed(self) -> None:
        idx = self._index_with("generic-xc7z020/pynq")
        entry = resolver.resolve_platform(idx, "pynq-z2/pynq")
        assert entry.platform == "generic-xc7z020/pynq"

    def test_corrupt_board_db_falls_back_to_resolution_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """壊れた user board-db は fallback をスキップし、従来の ResolutionError に落とす.

        fallback は加算的変更: board-db 破損 (不正 YAML / schema 不一致 / boardpart
        重複) が未処理トレースバックとして CLI まで漏れてはならない (早期
        レビュー S-1)。従来どおり exit 5 経路の ResolutionError になること。
        """
        bad_yaml = tmp_path / "official.yaml"
        bad_yaml.write_text("boards: [unclosed", encoding="utf-8")
        monkeypatch.setattr("fabricgate.models.board_db._DEFAULT_OFFICIAL", bad_yaml)
        monkeypatch.setattr("fabricgate.models.board_db._DEFAULT_CUSTOM", tmp_path / "nope.yaml")
        idx = self._index_with("generic-xc7z020/pynq")
        with pytest.raises(resolver.ResolutionError, match="not found"):
            resolver.resolve_platform_detailed(idx, "pynq-z2/pynq")

    def test_programming_error_in_lookup_propagates(self) -> None:
        """lookup 中の TypeError 等のプログラミングエラーは ResolutionError に化けない.

        破損系 (OSError / ValueError / yaml.YAMLError) のみ捕捉する契約の固定
        (レビュー: broad except がバグを隠さないこと)。
        """

        class BrokenDb:
            def lookup(self, board_id: str) -> None:
                raise TypeError("bug in lookup")

        idx = self._index_with("generic-xc7z020/pynq")
        with pytest.raises(TypeError, match="bug in lookup"):
            resolver.resolve_platform_detailed(idx, "pynq-z2/pynq", board_db=BrokenDb())  # type: ignore[arg-type]


# ============================================================================
# cache
# ============================================================================


class TestCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        idx = CacheIndex()
        cache.save_index(idx, tmp_path)
        loaded = cache.load_index(tmp_path)
        assert loaded.entries == []

    def test_store_and_lookup(self, tmp_path: Path) -> None:
        art_dir = tmp_path / "ns" / "design" / "1.0.0" / "xc7z020" / "pynq"
        art_dir.mkdir(parents=True)
        entry = cache.store(
            "ns/design",
            "1.0.0",
            "xc7z020/pynq",
            _FAKE_DIGEST,
            art_dir,
            tmp_path,
        )
        assert entry.name == "ns/design"
        found = cache.lookup("ns/design", "1.0.0", "xc7z020/pynq", tmp_path)
        assert found is not None
        assert found.digest == _FAKE_DIGEST

    def test_lookup_miss(self, tmp_path: Path) -> None:
        assert cache.lookup("x/y", "0.0.1", "foo/bar", tmp_path) is None

    def test_store_replaces_stale(self, tmp_path: Path) -> None:
        art_dir = tmp_path / "data"
        art_dir.mkdir()
        digest1 = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        digest2 = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
        cache.store("a/b", "1.0.0", "d/r", digest1, art_dir, tmp_path)
        cache.store("a/b", "1.0.0", "d/r", digest2, art_dir, tmp_path)
        idx = cache.load_index(tmp_path)
        assert len(idx.entries) == 1
        assert idx.entries[0].digest == digest2

    def test_platform_dir(self) -> None:
        p = cache.platform_dir("ns/design", "1.0.0", "xc7z020/pynq", Path("/cache"))
        assert p == Path("/cache/ns/design/1.0.0/xc7z020/pynq")


# ============================================================================
# publisher
# ============================================================================


class TestPublisher:
    def _write_project(self, root: Path) -> None:
        """Create a minimal publishable project."""
        platform_dir = root / "xc7z020" / "pynq"
        platform_dir.mkdir(parents=True)

        # Write a bitstream file
        bitstream_content = b"\x00\x01\x02\x03"
        (platform_dir / "design.bit").write_bytes(bitstream_content)
        bit_sha = hashlib.sha256(bitstream_content).hexdigest()

        # Write an hwh file
        hwh_content = b"<hwh/>"
        (platform_dir / "design.hwh").write_bytes(hwh_content)
        hwh_sha = hashlib.sha256(hwh_content).hexdigest()

        manifest_data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "pynq",
            "board": "pynq-z2",
            "design_ref": "test-ns/blink:1.0.0",
            "artifacts": {
                "bitstream": {"file": "design.bit", "sha256": bit_sha},
                "hwh": {"file": "design.hwh", "sha256": hwh_sha},
            },
        }
        (platform_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest_data))

        manifest_bytes = (platform_dir / "manifest.yaml").read_bytes()
        manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"

        idx_data = {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Test design",
            "platforms": [
                {"platform": "xc7z020/pynq", "digest": manifest_digest},
            ],
        }
        (root / "fabricgate-index.yaml").write_text(yaml.safe_dump(idx_data))

    def test_load_design_index(self, tmp_path: Path) -> None:
        self._write_project(tmp_path)
        idx, p = load_design_index(tmp_path)
        assert idx.name == "test-ns/blink"
        assert "fabricgate-index" in p.name

    def test_load_design_index_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(PublishError, match="No fabricgate-index"):
            load_design_index(tmp_path)

    def test_collect_artifacts(self, tmp_path: Path) -> None:
        self._write_project(tmp_path)
        idx, _ = load_design_index(tmp_path)
        files = collect_artifacts(tmp_path, idx)
        assert "index" in files
        assert "platform:xc7z020/pynq:manifest" in files
        assert "platform:xc7z020/pynq:artifact:design.bit" in files
        assert "platform:xc7z020/pynq:artifact:design.hwh" in files

    def test_collect_missing_manifest(self, tmp_path: Path) -> None:
        idx_data = {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Test",
            "platforms": [
                {"platform": "missing/platform", "digest": _FAKE_DIGEST},
            ],
        }
        (tmp_path / "fabricgate-index.yaml").write_text(yaml.safe_dump(idx_data))
        idx, _ = load_design_index(tmp_path)
        with pytest.raises(PublishError, match="Manifest not found"):
            collect_artifacts(tmp_path, idx)

    def test_read_yaml_non_dict(self, tmp_path: Path) -> None:
        """YAML ファイルが mapping でないとき PublishError を送出する (lines 35-36)。"""
        from fabricgate.client.publisher import _read_yaml

        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(PublishError, match="not a valid YAML mapping"):
            _read_yaml(f)

    def test_collect_artifact_not_found(self, tmp_path: Path) -> None:
        """アーティファクトファイルが存在しないとき PublishError を送出する (lines 104-105)。"""
        platform_dir = tmp_path / "xc7z020" / "pynq"
        platform_dir.mkdir(parents=True)
        manifest_data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "pynq",
            "board": "pynq-z2",
            "design_ref": "test-ns/blink:1.0.0",
            "artifacts": {
                "bitstream": {"file": "missing.bit", "sha256": "a" * 64},
                "hwh": {"file": "missing.hwh", "sha256": "b" * 64},
            },
        }
        (platform_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest_data))
        manifest_bytes = (platform_dir / "manifest.yaml").read_bytes()
        manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
        idx_data = {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Test",
            "platforms": [{"platform": "xc7z020/pynq", "digest": manifest_digest}],
        }
        (tmp_path / "fabricgate-index.yaml").write_text(yaml.safe_dump(idx_data))
        idx, _ = load_design_index(tmp_path)
        with pytest.raises(PublishError, match="Artifact not found"):
            collect_artifacts(tmp_path, idx)

    def test_collect_artifact_digest_mismatch(self, tmp_path: Path) -> None:
        """アーティファクトのsha256が合わないとき PublishError を送出する (lines 120-121)。"""
        platform_dir = tmp_path / "xc7z020" / "pynq"
        platform_dir.mkdir(parents=True)
        # Write real bitstream + hwh files
        (platform_dir / "design.bit").write_bytes(b"\x00\x01\x02\x03")
        (platform_dir / "design.hwh").write_bytes(b"<hwh/>")
        # Manifest with wrong (non-placeholder) sha256 — must not be all-same-char
        wrong_sha = "0" * 63 + "1"  # 64 chars, two distinct chars → not a placeholder
        manifest_data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "pynq",
            "board": "pynq-z2",
            "design_ref": "test-ns/blink:1.0.0",
            "artifacts": {
                "bitstream": {"file": "design.bit", "sha256": wrong_sha},
                "hwh": {"file": "design.hwh", "sha256": wrong_sha},
            },
        }
        (platform_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest_data))
        manifest_bytes = (platform_dir / "manifest.yaml").read_bytes()
        manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
        idx_data = {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Test",
            "platforms": [{"platform": "xc7z020/pynq", "digest": manifest_digest}],
        }
        (tmp_path / "fabricgate-index.yaml").write_text(yaml.safe_dump(idx_data))
        idx, _ = load_design_index(tmp_path)
        with pytest.raises(PublishError, match="Digest mismatch"):
            collect_artifacts(tmp_path, idx)

    def test_collect_kernel_module_artifacts(self, tmp_path: Path) -> None:
        """linux-fpgamgr の modules リスト型フィールドのアーティファクトも収集される (lines 138-141)。"""
        platform_dir = tmp_path / "xc7z020" / "linux-fpgamgr"
        platform_dir.mkdir(parents=True)
        # Write real bitstream and kernel module files
        bit_bytes = b"\x00\x01\x02\x03"
        (platform_dir / "design.bin").write_bytes(bit_bytes)
        ko_bytes = b"kernel-module-content"
        (platform_dir / "mymodule.ko").write_bytes(ko_bytes)
        # Compute real digests
        bit_sha = hashlib.sha256(bit_bytes).hexdigest()
        ko_sha = hashlib.sha256(ko_bytes).hexdigest()
        manifest_data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "test-board",
            "design_ref": "test-ns/blink:1.0.0",
            "artifacts": {
                "bitstream": {"file": "design.bin", "sha256": bit_sha},
                "modules": [{"file": "mymodule.ko", "sha256": ko_sha, "module_name": "mymodule"}],
            },
        }
        (platform_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest_data))
        manifest_bytes = (platform_dir / "manifest.yaml").read_bytes()
        manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
        idx_data = {
            "schema": "fabricgate-index/v1",
            "name": "test-ns/blink",
            "version": "1.0.0",
            "summary": "Test",
            "platforms": [{"platform": "xc7z020/linux-fpgamgr", "digest": manifest_digest}],
        }
        (tmp_path / "fabricgate-index.yaml").write_text(yaml.safe_dump(idx_data))
        idx, _ = load_design_index(tmp_path)
        files = collect_artifacts(tmp_path, idx)
        platform_key = "xc7z020/linux-fpgamgr"
        assert f"platform:{platform_key}:artifact:design.bin" in files
        assert f"platform:{platform_key}:artifact:mymodule.ko" in files
