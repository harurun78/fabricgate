"""Unit tests for models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from fabricgate._version import __version__
from fabricgate.models.cli import (
    CacheEntry,
    CacheIndex,
    Credentials,
    DesignInfo,
    PullResult,
    RegistryConfig,
    SearchResult,
    VerificationItem,
    VerificationResult,
)
from fabricgate.models.common import (
    SPDX_LICENSE_IDS,
    Pagination,
    SpdxExpression,
    SpeedGrade,
    extract_spdx_identifiers,
    find_unknown_spdx_ids,
)
from fabricgate.models.design_index import DesignIndex, PlatformEntry
from fabricgate.models.platform_manifest import (
    ArtifactRef,
    Interface,
    LinuxFpgamgrManifest,
    NanopynqManifest,
    PynqManifest,
    parse_platform_manifest,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def test_version():
    assert __version__ == "0.1.0"


# ---------------------------------------------------------------------------
# common.py
# ---------------------------------------------------------------------------


class TestCommonTypes:
    def test_speed_grade(self):
        sg = SpeedGrade(min="-2", tested=["-2", "-3"])
        assert sg.min == "-2"
        assert sg.tested == ["-2", "-3"]

    def test_pagination(self):
        p = Pagination(total=100, page=1, per_page=20)
        assert p.total == 100

    def test_pagination_invalid(self):
        with pytest.raises(ValidationError):
            Pagination(total=-1, page=1, per_page=20)

    def test_fabricgate_model_forbids_extra(self):
        with pytest.raises(ValidationError):
            SpeedGrade(min="-1", unknown_field="bad")


class TestApiResponseExtraPolicy:
    """ADR-014: API response models tolerate unknown fields (tolerant reader);
    request / local-validation models keep extra="forbid"."""

    @staticmethod
    def _minimal_version_detail_payload() -> dict:
        return {
            "schema": "fabricgate-index/v1",
            "name": "acme/blink",
            "version": "1.0.0",
            "platforms": [
                {
                    "platform": "xczu7ev/pynq",
                    "digest": "sha256:" + "ab" * 32,
                }
            ],
            "published_at": datetime(2026, 1, 1, tzinfo=UTC),
        }

    def test_version_detail_response_unknown_top_level_field_ignored(self):
        """Unknown top-level field in an API response payload is ignored, not rejected."""
        from fabricgate.models.api.responses import VersionDetailResponse

        payload = self._minimal_version_detail_payload()
        payload["x_future_field"] = "added-by-newer-registry"

        resp = VersionDetailResponse.model_validate(payload)

        assert resp.name == "acme/blink"
        assert not hasattr(resp, "x_future_field")

    def test_api_platform_entry_unknown_nested_field_ignored(self):
        """Unknown field nested in platforms[] (ApiPlatformEntry) is ignored."""
        from fabricgate.models.api.responses import VersionDetailResponse

        payload = self._minimal_version_detail_payload()
        payload["platforms"][0]["x_future_field"] = "ignored"

        resp = VersionDetailResponse.model_validate(payload)

        assert resp.platforms[0].platform == "xczu7ev/pynq"
        assert not hasattr(resp.platforms[0], "x_future_field")

    def test_error_response_unknown_fields_ignored(self):
        """ErrorResponse tolerates unknown fields at both nesting levels."""
        from fabricgate.models.api.errors import ErrorResponse

        resp = ErrorResponse.model_validate(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "design not found",
                    "unknown": "extra-detail",
                },
                "unknown_top": True,
            }
        )

        assert resp.error.code == "NOT_FOUND"
        assert resp.error.message == "design not found"

    def test_request_model_still_forbids_extra(self):
        """Request models keep extra="forbid" (strict external input validation)."""
        from fabricgate.models.api.requests import YankRequest

        with pytest.raises(ValidationError):
            YankRequest.model_validate({"reason": "bad build", "unknown_field": "x"})

    def test_local_platform_entry_still_forbids_extra(self):
        """Local Design Index PlatformEntry keeps extra="forbid" (contrast to ApiPlatformEntry)."""
        with pytest.raises(ValidationError):
            PlatformEntry.model_validate(
                {
                    "platform": "xczu7ev/pynq",
                    "digest": "sha256:" + "ab" * 32,
                    "unknown_field": "x",
                }
            )

    def test_api_response_model_inherits_strict(self):
        """ApiResponseModel inherits strict=True: type coercion stays disallowed."""
        from fabricgate.models.api.errors import ErrorDetail

        with pytest.raises(ValidationError):
            ErrorDetail(code=123, message="x")

    def test_api_platform_entry_inherits_strict(self):
        """ApiPlatformEntry keeps strict=True despite its own ConfigDict override."""
        from fabricgate.models.api.responses import ApiPlatformEntry

        entry = self._minimal_version_detail_payload()["platforms"][0]
        entry["size"] = "123"  # str where int expected

        with pytest.raises(ValidationError):
            ApiPlatformEntry.model_validate(entry)


class TestSpdxExpression:
    """SPDX license expression validation (MODEL-SPDX-001)."""

    @pytest.mark.parametrize(
        "expr",
        [
            "MIT",
            "Apache-2.0",
            "GPL-2.0-only",
            "BSD-3-Clause",
            "MIT AND Apache-2.0",
            "MIT OR GPL-2.0-only",
            "GPL-2.0-only WITH Classpath-exception-2.0",
            "LicenseRef-custom",
            "MIT AND Apache-2.0 AND BSD-3-Clause",
        ],
    )
    def test_valid_expressions(self, expr):
        """Valid SPDX expressions pass validation."""
        from pydantic import TypeAdapter

        ta = TypeAdapter(SpdxExpression)
        assert ta.validate_python(expr) == expr

    @pytest.mark.parametrize(
        "expr",
        [
            "",
            " ",
            "MIT AND",
            "AND MIT",
            "MIT and Apache-2.0",
            "MIT/Apache-2.0",
        ],
    )
    def test_invalid_expressions(self, expr):
        """Invalid SPDX expressions fail validation."""
        from pydantic import TypeAdapter

        ta = TypeAdapter(SpdxExpression)
        with pytest.raises(ValidationError):
            ta.validate_python(expr)

    def test_none_allowed(self):
        """None is allowed (license unspecified)."""
        data = _minimal_index_data()
        data["license"] = None
        idx = DesignIndex.model_validate(data)
        assert idx.license is None

    def test_omitted_allowed(self):
        """Omitting license entirely is allowed."""
        data = _minimal_index_data()
        assert "license" not in data
        idx = DesignIndex.model_validate(data)
        assert idx.license is None

    def test_empty_string_rejected(self):
        """Empty string is not permitted for license."""
        data = _minimal_index_data()
        data["license"] = ""
        with pytest.raises(ValidationError):
            DesignIndex.model_validate(data)

    def test_max_length_512(self):
        """License field respects max_length=512."""
        from pydantic import TypeAdapter

        ta = TypeAdapter(SpdxExpression)
        long_expr = "MIT" + " AND Apache-2.0" * 40  # Well over 512 chars
        assert len(long_expr) > 512
        with pytest.raises(ValidationError):
            ta.validate_python(long_expr)

    def test_design_detail_response_spdx(self):
        """DesignDetailResponse also validates SPDX."""
        from fabricgate.models.api.responses import DesignDetailResponse

        with pytest.raises(ValidationError):
            DesignDetailResponse(
                name="test-ns/test",
                license="",
                versions=[],
                created_at=datetime.now(tz=UTC),
            )

    def test_design_info_spdx(self):
        """DesignInfo also validates SPDX."""
        with pytest.raises(ValidationError):
            DesignInfo(
                name="fabricgate/blink",
                version="1.0.0",
                license="",
                platforms=[
                    PlatformEntry(
                        platform="xczu7ev/pynq",
                        digest="sha256:" + "aa" * 32,
                    )
                ],
            )

    def test_version_detail_response_spdx(self):
        """VersionDetailResponse also validates SPDX."""
        from fabricgate.models.api.responses import VersionDetailResponse

        with pytest.raises(ValidationError):
            VersionDetailResponse(
                name="test-ns/test",
                version="1.0.0",
                license="",
                platforms=[],
                published_at=datetime.now(tz=UTC),
            )


# ---------------------------------------------------------------------------
# design_index.py
# ---------------------------------------------------------------------------


def _minimal_index_data() -> dict:
    return {
        "schema": "fabricgate-index/v1",
        "name": "test-ns/test-design",
        "version": "1.0.0",
        "platforms": [
            {
                "platform": "xczu7ev/pynq",
                "digest": "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
            }
        ],
    }


class TestSpdxKnownIdentifiers:
    """SCH-SPDX-001: SPDX known-identifier warning validation."""

    def test_known_id_no_warning(self, caplog):
        """Known SPDX identifier does not produce a warning."""
        import logging

        data = _minimal_index_data()
        data["license"] = "MIT"
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            DesignIndex.model_validate(data)
        assert caplog.text == ""

    def test_unknown_id_warning(self, caplog):
        """Unknown SPDX identifier produces a warning."""
        import logging

        data = _minimal_index_data()
        data["license"] = "UnknownLicense-99"
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            idx = DesignIndex.model_validate(data)
        assert idx.license == "UnknownLicense-99"
        assert "UnknownLicense-99" in caplog.text
        assert "not in the published SPDX license list" in caplog.text

    def test_unknown_id_not_rejected(self):
        """Unknown SPDX identifier is accepted (not rejected)."""
        data = _minimal_index_data()
        data["license"] = "FooBar-1.0"
        idx = DesignIndex.model_validate(data)
        assert idx.license == "FooBar-1.0"

    def test_compound_with_unknown_warns_only_unknown(self, caplog):
        """Compound expression warns only for the unknown part."""
        import logging

        data = _minimal_index_data()
        data["license"] = "MIT AND FakeLicense-2.0"
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            DesignIndex.model_validate(data)
        assert "FakeLicense-2.0" in caplog.text
        assert "MIT" not in caplog.text.replace("MIT AND FakeLicense-2.0", "")

    def test_licenseref_always_accepted(self, caplog):
        """LicenseRef-* user-defined references produce no warning."""
        import logging

        data = _minimal_index_data()
        data["license"] = "LicenseRef-proprietary"
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            idx = DesignIndex.model_validate(data)
        assert idx.license == "LicenseRef-proprietary"
        assert caplog.text == ""

    def test_none_license_no_warning(self, caplog):
        """None license produces no warning."""
        import logging

        data = _minimal_index_data()
        data["license"] = None
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            DesignIndex.model_validate(data)
        assert caplog.text == ""

    def test_omitted_license_no_warning(self, caplog):
        """Omitted license produces no warning."""
        import logging

        data = _minimal_index_data()
        with caplog.at_level(logging.WARNING, logger="fabricgate.models.design_index"):
            DesignIndex.model_validate(data)
        assert caplog.text == ""


class TestExtractSpdxIdentifiers:
    """Unit tests for extract_spdx_identifiers."""

    def test_single(self):
        assert extract_spdx_identifiers("MIT") == ["MIT"]

    def test_compound_and(self):
        assert extract_spdx_identifiers("MIT AND Apache-2.0") == ["MIT", "Apache-2.0"]

    def test_compound_or(self):
        assert extract_spdx_identifiers("MIT OR GPL-2.0-only") == [
            "MIT",
            "GPL-2.0-only",
        ]

    def test_with_exception(self):
        result = extract_spdx_identifiers("GPL-2.0-only WITH Classpath-exception-2.0")
        assert result == ["GPL-2.0-only", "Classpath-exception-2.0"]

    def test_triple(self):
        result = extract_spdx_identifiers("MIT AND Apache-2.0 AND BSD-3-Clause")
        assert result == ["MIT", "Apache-2.0", "BSD-3-Clause"]


class TestFindUnknownSpdxIds:
    """Unit tests for find_unknown_spdx_ids."""

    def test_all_known(self):
        assert find_unknown_spdx_ids("MIT AND Apache-2.0") == []

    def test_one_unknown(self):
        assert find_unknown_spdx_ids("MIT AND FakeLicense-1.0") == ["FakeLicense-1.0"]

    def test_licenseref_accepted(self):
        assert find_unknown_spdx_ids("LicenseRef-custom") == []

    def test_spdx_list_has_common_ids(self):
        common = {"MIT", "Apache-2.0", "GPL-3.0-only", "BSD-3-Clause", "ISC"}
        assert common.issubset(SPDX_LICENSE_IDS)

    def test_unknown_spdx_exception_id(self):
        """未知の WITH 例外 ID → unknown リストに含まれる (lines 318-320)。"""
        result = find_unknown_spdx_ids("GPL-2.0-only WITH UnknownException-1.0")
        assert "UnknownException-1.0" in result


class TestDesignIndex:
    """Design Index model tests."""

    def test_minimal_valid(self):
        idx = DesignIndex.model_validate(_minimal_index_data())
        assert idx.name == "test-ns/test-design"
        assert idx.version == "1.0.0"
        assert len(idx.platforms) == 1

    def test_full_metadata(self):
        data = _minimal_index_data()
        data.update(
            summary="Test design",
            license="MIT",
            author="Test Author",
            tags=["test", "demo"],
        )
        idx = DesignIndex.model_validate(data)
        assert idx.summary == "Test design"
        assert idx.tags == ["test", "demo"]

    def test_duplicate_platform_rejected(self):
        data = _minimal_index_data()
        data["platforms"].append(data["platforms"][0].copy())
        with pytest.raises(ValidationError, match="Duplicate platform"):
            DesignIndex.model_validate(data)

    def test_empty_platforms_rejected(self):
        data = _minimal_index_data()
        data["platforms"] = []
        with pytest.raises(ValidationError):
            DesignIndex.model_validate(data)

    def test_invalid_name_format(self):
        data = _minimal_index_data()
        data["name"] = "UPPERCASE/bad"
        with pytest.raises(ValidationError):
            DesignIndex.model_validate(data)

    def test_invalid_version_format(self):
        data = _minimal_index_data()
        data["version"] = "1.0.0-alpha"
        with pytest.raises(ValidationError):
            DesignIndex.model_validate(data)

    def test_invalid_schema(self):
        data = _minimal_index_data()
        data["schema"] = "fabricgate-index/v2"
        with pytest.raises(ValidationError):
            DesignIndex.model_validate(data)

    def test_yaml_roundtrip(self):
        idx = DesignIndex.model_validate(_minimal_index_data())
        yaml_str = idx.to_yaml()
        idx2 = DesignIndex.from_yaml(yaml_str)
        assert idx2.name == idx.name
        assert idx2.version == idx.version
        assert idx2.platforms[0].digest == idx.platforms[0].digest

    def test_from_fixture_yaml(self):
        content = (FIXTURES / "sample_index.yaml").read_text()
        idx = DesignIndex.from_yaml(content)
        assert idx.name == "fabricgate/blink"
        assert idx.version == "1.0.0"
        assert len(idx.platforms) == 2

    def test_extra_fields_ignored(self):
        data = _minimal_index_data()
        data["future_field"] = "should be ignored"
        idx = DesignIndex.model_validate(data)
        assert idx.name == "test-ns/test-design"

    # ------------------------------------------------------------------
    # XSS / unsafe HTML rejection tests
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            "<Script SRC=http://evil.com/xss.js></Script>",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(document.cookie)>",
            "<iframe src=javascript:alert(1)>",
            "<b>bold</b>",
            "onclick=alert(1)",
            "onerror=evil()",
            "onmouseover = bad()",
            "javascript:void(0)",
            "JAVASCRIPT:alert('xss')",
            "vbscript:msgbox(1)",
            "<!--comment-->",
            "<!DOCTYPE html>",
        ],
    )
    def test_summary_rejects_unsafe_html(self, payload: str) -> None:
        data = _minimal_index_data()
        data["summary"] = payload
        with pytest.raises(ValidationError, match="HTML tags and unsafe content"):
            DesignIndex.model_validate(data)

    @pytest.mark.parametrize(
        "safe_text",
        [
            "# Markdown heading",
            "**bold** and *italic*",
            "`code snippet`",
            "A & B comparison",
            "Score: 100%",
            "Works with voltage ≥ 1.8V",
            "High-speed FPGA design v2.0",
            "Supports on-board LEDs",
        ],
    )
    def test_summary_allows_safe_text(self, safe_text: str) -> None:
        data = _minimal_index_data()
        data["summary"] = safe_text
        idx = DesignIndex.model_validate(data)
        assert idx.summary == safe_text

    def test_summary_none_allowed(self) -> None:
        data = _minimal_index_data()
        # summary defaults to None — should pass validation
        idx = DesignIndex.model_validate(data)
        assert idx.summary is None


class TestNamespaceCreateRequestHtmlSafety:
    """HTML safety validation tests for NamespaceCreateRequest."""

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert(1)>",
            "onclick=stealCookies()",
            "javascript:alert(document.cookie)",
            "vbscript:evil()",
            "<b>some bold text</b>",
        ],
    )
    def test_description_rejects_unsafe_html(self, payload: str) -> None:
        from fabricgate.models.api.requests import NamespaceCreateRequest

        with pytest.raises(ValidationError, match="HTML tags and unsafe content"):
            NamespaceCreateRequest.model_validate({"name": "test-ns", "display_name": "Test", "description": payload})

    @pytest.mark.parametrize(
        "safe_text",
        [
            "A simple namespace for FPGA designs.",
            "Supports ## Markdown and **bold** text.",
            "Temperature range: -40°C to +85°C",
            "Power consumption < 5W",
            "",
        ],
    )
    def test_description_allows_safe_text(self, safe_text: str) -> None:
        from fabricgate.models.api.requests import NamespaceCreateRequest

        req = NamespaceCreateRequest.model_validate(
            {"name": "test-ns", "display_name": "Test", "description": safe_text}
        )
        assert req.description == safe_text

    def test_with_speed_grade(self):
        entry = PlatformEntry.model_validate(
            {
                "platform": "zcu104/pynq",
                "digest": "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
                "size": 256000,
                "speed_grade": {"min": "-2", "tested": ["-2"]},
            }
        )
        assert entry.speed_grade is not None
        assert entry.speed_grade.min == "-2"

    def test_with_shell_dependency(self):
        entry = PlatformEntry.model_validate(
            {
                "platform": "zcu104/pynq",
                "digest": "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
                "shell_dependency": {"name": "acme/shell", "version": "=1.2.3", "sha256": "ab" * 32},
            }
        )
        assert entry.shell_dependency is not None
        assert entry.shell_dependency.name == "acme/shell"
        assert entry.shell_dependency.version == "=1.2.3"
        assert entry.shell_dependency.sha256 == "ab" * 32

    def test_shell_dependency_requires_sha256(self):
        """SG-1: the ADR-009 sha256 pin is mandatory on shell_dependency."""
        with pytest.raises(ValidationError):
            PlatformEntry.model_validate(
                {
                    "platform": "zcu104/pynq",
                    "digest": "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
                    "shell_dependency": {"name": "acme/shell", "version": "=1.2.3"},
                }
            )

    def test_without_shell_dependency(self):
        entry = PlatformEntry.model_validate(
            {
                "platform": "zcu104/pynq",
                "digest": "sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
            }
        )
        assert entry.shell_dependency is None

    def test_invalid_digest(self):
        with pytest.raises(ValidationError):
            PlatformEntry.model_validate(
                {
                    "platform": "zcu104/pynq",
                    "digest": "md5:abc123",
                }
            )


# ---------------------------------------------------------------------------
# platform_manifest.py
# ---------------------------------------------------------------------------


def _pynq_manifest_data() -> dict:
    return {
        "schema": "fabricgate-platform/v1",
        "runtime": "pynq",
        "board": "zcu104",
        "design_ref": "fabricgate/blink:1.0.0",
        "artifacts": {
            "bitstream": {
                "file": "blink.bit",
                "sha256": "aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
            },
            "hwh": {
                "file": "blink.hwh",
                "sha256": "11223344112233441122334411223344112233441122334411223344112233aa",
            },
        },
    }


class TestPynqManifest:
    def test_valid(self):
        m = PynqManifest.model_validate(_pynq_manifest_data())
        assert m.runtime == "pynq"
        assert m.board == "zcu104"

    def test_device_family_optional(self):
        data = {**_pynq_manifest_data(), "device_family": "xczu7ev"}
        m = PynqManifest.model_validate(data)
        assert m.device_family == "xczu7ev"

    def test_status_deprecated(self):
        data = {**_pynq_manifest_data(), "bitstream_type": "shell", "status": "deprecated"}
        m = PynqManifest.model_validate(data)
        assert m.status == "deprecated"

    def test_status_yanked(self):
        data = {**_pynq_manifest_data(), "bitstream_type": "shell", "status": "yanked"}
        m = PynqManifest.model_validate(data)
        assert m.status == "yanked"

    def test_status_invalid_rejected(self):
        data = {**_pynq_manifest_data(), "status": "active"}
        with pytest.raises(ValidationError):
            PynqManifest.model_validate(data)

    def test_design_portability_valid(self):
        data = {**_pynq_manifest_data(), "design_portability": "axi-only"}
        m = PynqManifest.model_validate(data)
        assert m.design_portability == "axi-only"

    def test_design_portability_invalid_rejected(self):
        data = {**_pynq_manifest_data(), "design_portability": "unknown"}
        with pytest.raises(ValidationError):
            PynqManifest.model_validate(data)

    def test_virtual_board_allowed(self):
        data = {**_pynq_manifest_data(), "board": "generic-xczu7ev"}
        m = PynqManifest.model_validate(data)
        assert m.board == "generic-xczu7ev"

    def test_missing_hwh_rejected(self):
        data = _pynq_manifest_data()
        del data["artifacts"]["hwh"]
        with pytest.raises(ValidationError):
            PynqManifest.model_validate(data)

    def test_from_fixture_yaml(self):
        content = (FIXTURES / "sample_manifest.yaml").read_text()
        m = parse_platform_manifest(content)
        assert isinstance(m, PynqManifest)
        assert m.board == "zcu104"
        assert m.device_family == "xczu7ev"
        assert len(m.tool_requirements) == 1
        assert m.tool_requirements[0].tool == "vivado"

    def test_extra_fields_ignored(self):
        data = _pynq_manifest_data()
        data["future_field"] = "ignored"
        m = PynqManifest.model_validate(data)
        assert m.runtime == "pynq"


class TestLinuxFpgamgrManifest:
    def test_valid_with_post_load(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011",
                },
            },
            "post_load": {
                "health_check": {
                    "type": "register-read",
                    "params": {"address": "0x41200000", "expected": "0x00000001"},
                },
            },
        }
        m = LinuxFpgamgrManifest.model_validate(data)
        assert m.post_load is not None
        assert m.post_load.health_check is not None
        assert m.post_load.health_check.type == "register-read"

    def test_device_family_optional(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "device_family": "xczu7ev",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011",
                },
            },
        }
        m = LinuxFpgamgrManifest.model_validate(data)
        assert m.device_family == "xczu7ev"

    def test_shell_dependency_not_allowed_with_non_partial(self):
        """bitstream_type != 'partial' かつ shell_dependency がある → ValidationError (line 231)。"""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "bitstream_type": "shell",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011",
                },
            },
            "shell_dependency": {"name": "acme/shell", "version": "=1.0.0", "sha256": "ab" * 32},
        }
        with pytest.raises(ValidationError, match="must not be set"):
            LinuxFpgamgrManifest.model_validate(data)


class TestBitstreamExtensionWarning:
    """ADR-011: unknown bitstream container extension warns (does not reject)."""

    _LOGGER = "fabricgate.models.platform_manifest"

    def test_pynq_bit_no_warning(self, caplog):
        """`.bit` is in the pynq allowlist — no warning."""
        import logging

        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            PynqManifest.model_validate(_pynq_manifest_data())
        assert caplog.text == ""

    def test_linux_fpgamgr_bin_no_warning(self, caplog):
        """`.bin` is in the linux-fpgamgr allowlist — no warning."""
        import logging

        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bin",
                    "sha256": "eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011",
                },
            },
        }
        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            LinuxFpgamgrManifest.model_validate(data)
        assert caplog.text == ""

    def test_pynq_unknown_extension_warns_but_validates(self, caplog):
        """Unknown extension on pynq produces a WARNING; validation still succeeds."""
        import logging

        data = _pynq_manifest_data()
        data["artifacts"]["bitstream"]["file"] = "blink.xyz"
        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            m = PynqManifest.model_validate(data)
        assert m.artifacts.bitstream.file == "blink.xyz"
        assert "blink.xyz" in caplog.text
        assert "pynq" in caplog.text

    def test_nanopynq_bin_no_warning(self, caplog):
        """`.bin` is in the nanopynq allowlist (raw iCE40 bitstream) — no warning."""
        import logging

        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bin",
                    "sha256": "2233445522334455223344552233445522334455223344552233445522334455",
                },
            },
            "transport": "spi",
            "mtu": 1024,
        }
        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            NanopynqManifest.model_validate(data)
        assert caplog.text == ""

    def test_nanopynq_bit_warns_but_validates(self, caplog):
        """§5.2: nanopynq's format is `.bin`, not `.bit` — `.bit` warns (still validates)."""
        import logging

        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "2233445522334455223344552233445522334455223344552233445522334455",
                },
            },
            "transport": "spi",
            "mtu": 1024,
        }
        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            m = NanopynqManifest.model_validate(data)
        assert m.artifacts.bitstream.file == "blink.bit"
        assert "blink.bit" in caplog.text
        assert "nanopynq" in caplog.text


class TestNanopynqManifest:
    def test_valid(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bin",
                    "sha256": "2233445522334455223344552233445522334455223344552233445522334455",
                },
            },
            "transport": "spi",
            "mtu": 1024,
        }
        m = NanopynqManifest.model_validate(data)
        assert m.transport == "spi"
        assert m.mtu == 1024

    def test_shell_dependency_not_allowed_with_non_partial(self):
        """bitstream_type != 'partial' かつ shell_dependency がある → ValidationError (line 305)。"""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "bitstream_type": "shell",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bin",
                    "sha256": "2233445522334455223344552233445522334455223344552233445522334455",
                },
            },
            "transport": "spi",
            "mtu": 1024,
            "shell_dependency": {"name": "acme/shell", "version": "=1.0.0", "sha256": "ab" * 32},
        }
        with pytest.raises(ValidationError, match="must not be set"):
            NanopynqManifest.model_validate(data)


class TestDiscriminatedUnion:
    def test_pynq_dispatch(self):
        import yaml

        content = yaml.safe_dump(_pynq_manifest_data(), sort_keys=False)
        m = parse_platform_manifest(content)
        assert isinstance(m, PynqManifest)

    def test_linux_dispatch(self):
        import yaml

        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011eeff0011",
                },
            },
        }
        content = yaml.safe_dump(data, sort_keys=False)
        m = parse_platform_manifest(content)
        assert isinstance(m, LinuxFpgamgrManifest)


class TestArtifactRef:
    def test_valid(self):
        a = ArtifactRef.model_validate(
            {
                "file": "design.bit",
                "sha256": "aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
            }
        )
        assert a.file == "design.bit"

    def test_invalid_sha256(self):
        with pytest.raises(ValidationError):
            ArtifactRef.model_validate(
                {
                    "file": "design.bit",
                    "sha256": "sha256:aabbccdd",  # should NOT have prefix
                }
            )


class TestInterface:
    def test_valid(self):
        i = Interface.model_validate(
            {
                "name": "axi_gpio_0",
                "type": "axi-lite",
                "base": "0x41200000",
            }
        )
        assert i.name == "axi_gpio_0"


# ---------------------------------------------------------------------------
# cli.py — CLI / SDK models (MODEL-CLI-001)
# ---------------------------------------------------------------------------


class TestRegistryConfig:
    def test_defaults(self):
        cfg = RegistryConfig()
        assert cfg.registry == "https://registry.fabricgate.dev/api/v1"
        assert cfg.platform is None
        assert cfg.cache_dir == "~/.fabricgate/cache"

    def test_custom_values(self):
        cfg = RegistryConfig(
            registry="https://custom.example.com/api/v1",
            platform="xczu7ev/pynq",
            cache_dir="/tmp/fg-cache",
        )
        assert cfg.registry == "https://custom.example.com/api/v1"
        assert cfg.platform == "xczu7ev/pynq"
        assert cfg.cache_dir == "/tmp/fg-cache"

    def test_invalid_platform_format(self):
        with pytest.raises(ValidationError):
            RegistryConfig(platform="INVALID")

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            RegistryConfig(unknown="bad")


class TestCredentials:
    def test_valid(self):

        cred = Credentials(
            registry="https://registry.fabricgate.dev/api/v1",
            token="eyJhbGci...",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            scopes=["public:read", "ns:alice:write"],
        )
        assert cred.registry == "https://registry.fabricgate.dev/api/v1"
        assert cred.token == "eyJhbGci..."
        assert len(cred.scopes) == 2

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            Credentials(registry="https://r.example.com", token="t")  # missing expires_at, scopes


class TestCacheEntry:
    def test_valid(self):

        entry = CacheEntry(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/home/user/.fabricgate/cache/fabricgate/blink/1.0.0/xczu7ev/pynq",
            pulled_at=datetime(2026, 3, 17, tzinfo=UTC),
            digest="sha256:aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd",
        )
        assert entry.name == "fabricgate/blink"
        assert entry.version == "1.0.0"
        assert entry.platform == "xczu7ev/pynq"

    def test_invalid_digest(self):

        with pytest.raises(ValidationError):
            CacheEntry(
                name="fabricgate/blink",
                version="1.0.0",
                platform="xczu7ev/pynq",
                path="/some/path",
                pulled_at=datetime(2026, 1, 1, tzinfo=UTC),
                digest="md5:abc",
            )

    def test_invalid_name_format(self):

        with pytest.raises(ValidationError):
            CacheEntry(
                name="INVALID",
                version="1.0.0",
                platform="xczu7ev/pynq",
                path="/p",
                pulled_at=datetime(2026, 1, 1, tzinfo=UTC),
                digest="sha256:" + "aa" * 32,
            )


class TestCacheIndex:
    def test_empty(self):
        idx = CacheIndex()
        assert idx.entries == []

    def test_with_entries(self):

        entry = CacheEntry(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/p",
            pulled_at=datetime(2026, 1, 1, tzinfo=UTC),
            digest="sha256:" + "aa" * 32,
        )
        idx = CacheIndex(entries=[entry])
        assert len(idx.entries) == 1


class TestPullResult:
    def test_valid(self):
        r = PullResult(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/home/user/designs/blink",
            artifacts=["bitstream.bit", "design.hwh"],
            cached=False,
        )
        assert r.name == "fabricgate/blink"
        assert len(r.artifacts) == 2
        assert r.cached is False

    def test_cached_hit(self):
        r = PullResult(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/cache/path",
            artifacts=["bitstream.bit"],
            cached=True,
        )
        assert r.cached is True

    def test_empty_artifacts(self):
        r = PullResult(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/p",
            artifacts=[],
            cached=False,
        )
        assert r.artifacts == []


class TestDesignInfoModel:
    def test_minimal(self):
        info = DesignInfo(
            name="fabricgate/blink",
            version="1.0.0",
            platforms=[
                PlatformEntry(
                    platform="xczu7ev/pynq",
                    digest="sha256:" + "aa" * 32,
                )
            ],
        )
        assert info.name == "fabricgate/blink"
        assert info.summary is None
        assert info.license is None
        assert info.tags == []

    def test_full_metadata(self):
        info = DesignInfo(
            name="fabricgate/blink",
            version="1.0.0",
            summary="LED blink",
            license="Apache-2.0",
            author="Test Author",
            repository="https://github.com/test/blink",
            tags=["blink", "led"],
            platforms=[
                PlatformEntry(
                    platform="xczu7ev/pynq",
                    digest="sha256:" + "aa" * 32,
                )
            ],
        )
        assert info.summary == "LED blink"
        assert info.license == "Apache-2.0"
        assert info.author == "Test Author"
        assert len(info.tags) == 2


class TestSearchResultModel:
    def test_valid(self):
        r = SearchResult(
            name="fabricgate/blink",
            version="1.0.0",
            summary="LED blink",
            platforms=["xczu7ev/pynq", "xczu7ev/linux-fpgamgr"],
        )
        assert r.name == "fabricgate/blink"
        assert len(r.platforms) == 2

    def test_optional_summary(self):
        r = SearchResult(
            name="fabricgate/blink",
            version="1.0.0",
            platforms=["xczu7ev/pynq"],
        )
        assert r.summary is None


class TestVerificationItem:
    def test_verified(self):
        v = VerificationItem(file="bitstream.bit", sha256="aa" * 32, verified=True)
        assert v.verified is True

    def test_not_verified(self):
        v = VerificationItem(file="bitstream.bit", sha256="aa" * 32, verified=False)
        assert v.verified is False


class TestVerificationResult:
    def test_valid(self):
        r = VerificationResult(
            design_ref="fabricgate/blink:1.0.0",
            platform="xczu7ev/pynq",
            directory="/home/user/designs/blink",
            artifacts=[
                VerificationItem(file="bitstream.bit", sha256="aa" * 32, verified=True),
                VerificationItem(file="design.hwh", sha256="bb" * 32, verified=True),
            ],
        )
        assert r.design_ref == "fabricgate/blink:1.0.0"
        assert len(r.artifacts) == 2
        assert all(a.verified for a in r.artifacts)

    def test_with_failed_artifact(self):
        r = VerificationResult(
            design_ref="fabricgate/blink:1.0.0",
            platform="xczu7ev/pynq",
            directory="/d",
            artifacts=[
                VerificationItem(file="bitstream.bit", sha256="aa" * 32, verified=True),
                VerificationItem(file="design.hwh", sha256="bb" * 32, verified=False),
            ],
        )
        assert not all(a.verified for a in r.artifacts)


class TestCLIModelSerialization:
    def test_registry_config_roundtrip(self):
        cfg = RegistryConfig(platform="xczu7ev/pynq")
        data = cfg.model_dump()
        cfg2 = RegistryConfig.model_validate(data)
        assert cfg2.platform == cfg.platform

    def test_cache_index_json_roundtrip(self):

        entry = CacheEntry(
            name="fabricgate/blink",
            version="1.0.0",
            platform="xczu7ev/pynq",
            path="/p",
            pulled_at=datetime(2026, 1, 1, tzinfo=UTC),
            digest="sha256:" + "aa" * 32,
        )
        idx = CacheIndex(entries=[entry])
        json_str = idx.model_dump_json()
        idx2 = CacheIndex.model_validate_json(json_str)
        assert len(idx2.entries) == 1
        assert idx2.entries[0].name == "fabricgate/blink"


# ---------------------------------------------------------------------------
# Dependency / ResolvedDependency / ShellDependency
# ---------------------------------------------------------------------------


class TestDependency:
    """MODEL-DEPS-001: Dependency model validation."""

    def test_valid_minimal(self):
        from fabricgate.models.platform_manifest import Dependency

        d = Dependency(name="acme/core", version="^1.0.0")
        assert d.name == "acme/core"
        assert d.version == "^1.0.0"
        assert d.platform is None
        assert d.optional is False

    @pytest.mark.parametrize(
        "version",
        [
            "*",
            "1.0.0",
            "^1.2.3",
            "~0.9.0",
            "^0.0.1",
            "~1.0.0",
        ],
    )
    def test_valid_version_constraints(self, version: str):
        from fabricgate.models.platform_manifest import Dependency

        d = Dependency(name="acme/core", version=version)
        assert d.version == version

    @pytest.mark.parametrize(
        "version",
        [
            "",
            "latest",
            "v1.0.0",
            ">=1.0",
            "abc",
        ],
    )
    def test_invalid_version_constraints(self, version: str):
        from fabricgate.models.platform_manifest import Dependency

        with pytest.raises(ValidationError):
            Dependency(name="acme/core", version=version)

    def test_with_platform_and_optional(self):
        from fabricgate.models.platform_manifest import Dependency

        d = Dependency(
            name="acme/dsp",
            version="~2.0.0",
            platform="xczu7ev/pynq",
            optional=True,
        )
        assert d.platform == "xczu7ev/pynq"
        assert d.optional is True

    def test_invalid_name_rejected(self):
        from fabricgate.models.platform_manifest import Dependency

        with pytest.raises(ValidationError):
            Dependency(name="INVALID", version="*")


class TestResolvedDependency:
    """MODEL-DEPS-001: ResolvedDependency model validation."""

    def test_valid(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        rd = ResolvedDependency(
            name="acme/core",
            resolved_version="1.2.3",
            platform="xczu7ev/pynq",
            optional=False,
            depth=1,
            required_by="acme/top:2.0.0",
        )
        assert rd.resolved_version == "1.2.3"
        assert rd.depth == 1

    def test_depth_zero_rejected(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        with pytest.raises(ValidationError):
            ResolvedDependency(
                name="acme/core",
                resolved_version="1.0.0",
                platform="xczu7ev/pynq",
                optional=False,
                depth=0,
                required_by="acme/top:1.0.0",
            )

    def test_invalid_resolved_version(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        with pytest.raises(ValidationError):
            ResolvedDependency(
                name="acme/core",
                resolved_version="not-semver",
                platform="xczu7ev/pynq",
                optional=False,
                depth=1,
                required_by="acme/top:1.0.0",
            )

    def test_depth_negative_rejected(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        with pytest.raises(ValidationError):
            ResolvedDependency(
                name="acme/core",
                resolved_version="1.0.0",
                platform="xczu7ev/pynq",
                optional=False,
                depth=-1,
                required_by="acme/top:1.0.0",
            )

    def test_depth_upper_bound_accepted(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        rd = ResolvedDependency(
            name="acme/core",
            resolved_version="1.0.0",
            platform="xczu7ev/pynq",
            optional=False,
            depth=100,
            required_by="acme/top:1.0.0",
        )
        assert rd.depth == 100

    def test_depth_over_upper_bound_rejected(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        with pytest.raises(ValidationError):
            ResolvedDependency(
                name="acme/core",
                resolved_version="1.0.0",
                platform="xczu7ev/pynq",
                optional=False,
                depth=101,
                required_by="acme/top:1.0.0",
            )

    def test_required_by_max_length_accepted(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        long_val = "a" * 256
        rd = ResolvedDependency(
            name="acme/core",
            resolved_version="1.0.0",
            platform="xczu7ev/pynq",
            optional=False,
            depth=1,
            required_by=long_val,
        )
        assert rd.required_by == long_val

    def test_required_by_over_max_length_rejected(self):
        from fabricgate.models.platform_manifest import ResolvedDependency

        with pytest.raises(ValidationError):
            ResolvedDependency(
                name="acme/core",
                resolved_version="1.0.0",
                platform="xczu7ev/pynq",
                optional=False,
                depth=1,
                required_by="a" * 257,
            )


class TestShellDependency:
    """MODEL-DEPS-001: ShellDependency model validation."""

    def test_valid_minimal(self):
        from fabricgate.models.platform_manifest import ShellDependency

        sd = ShellDependency(name="acme/shell", version="=1.0.0", sha256="ab" * 32)
        assert sd.version == "=1.0.0"
        assert sd.sha256 == "ab" * 32

    def test_rejects_missing_sha256(self):
        """SG-1: the ADR-009 sha256 pin is mandatory."""
        from fabricgate.models.platform_manifest import ShellDependency

        with pytest.raises(ValidationError):
            ShellDependency(name="acme/shell", version="=1.0.0")

    def test_valid_with_sha256(self):
        from fabricgate.models.platform_manifest import ShellDependency

        sd = ShellDependency(
            name="acme/shell",
            version="=2.3.4",
            sha256="aa" * 32,
        )
        assert sd.sha256 == "aa" * 32

    @pytest.mark.parametrize(
        "version",
        [
            "1.0.0",
            "^1.0.0",
            "~1.0.0",
            "*",
            ">=1.0.0",
        ],
    )
    def test_rejects_non_exact_version(self, version: str):
        from fabricgate.models.platform_manifest import ShellDependency

        with pytest.raises(ValidationError):
            ShellDependency(name="acme/shell", version=version, sha256="ab" * 32)

    def test_rejects_invalid_sha256(self):
        from fabricgate.models.platform_manifest import ShellDependency

        with pytest.raises(ValidationError):
            ShellDependency(
                name="acme/shell",
                version="=1.0.0",
                sha256="not-a-hex-digest",
            )

    def test_rejects_uppercase_sha256(self):
        from fabricgate.models.platform_manifest import ShellDependency

        with pytest.raises(ValidationError):
            ShellDependency(
                name="acme/shell",
                version="=1.0.0",
                sha256="AA" * 32,
            )


# ---------------------------------------------------------------------------
# ToolRequirement / Attestation (MODEL-PR-001)
# ---------------------------------------------------------------------------


class TestToolRequirement:
    """MODEL-PR-001: ToolRequirement model validation."""

    def test_valid_minimal(self):
        from fabricgate.models.platform_manifest import ToolRequirement

        t = ToolRequirement(tool="vivado")
        assert t.tool == "vivado"
        assert t.required is True
        assert t.min_version is None
        assert t.edition is None
        assert t.note is None

    def test_valid_full(self):
        from fabricgate.models.platform_manifest import ToolRequirement

        t = ToolRequirement(
            tool="vivado",
            min_version="2024.1",
            edition="enterprise",
            required=False,
            note="Used for synthesis only",
        )
        assert t.edition == "enterprise"
        assert t.required is False

    @pytest.mark.parametrize("tool", ["Vivado", "123abc", "a b", ""])
    def test_invalid_tool_name(self, tool: str):
        from fabricgate.models.platform_manifest import ToolRequirement

        with pytest.raises(ValidationError):
            ToolRequirement(tool=tool)

    @pytest.mark.parametrize("tool", ["vivado", "f4pga", "quartus", "vitis", "a0-b"])
    def test_valid_tool_names(self, tool: str):
        from fabricgate.models.platform_manifest import ToolRequirement

        assert ToolRequirement(tool=tool).tool == tool

    def test_note_max_length(self):
        from fabricgate.models.platform_manifest import ToolRequirement

        t = ToolRequirement(tool="vivado", note="x" * 256)
        assert len(t.note) == 256

        with pytest.raises(ValidationError):
            ToolRequirement(tool="vivado", note="x" * 257)


class TestAttestation:
    """MODEL-PR-001: Attestation model validation."""

    def test_valid(self):
        from fabricgate.models.platform_manifest import Attestation

        a = Attestation(
            bundle="cosign.bundle",
            transparency_log_url="https://rekor.sigstore.dev",
        )
        assert a.bundle == "cosign.bundle"

    def test_invalid_bundle_chars(self):
        from fabricgate.models.platform_manifest import Attestation

        with pytest.raises(ValidationError):
            Attestation(
                bundle="path/to/file",
                transparency_log_url="https://rekor.sigstore.dev",
            )

    def test_invalid_url_not_https(self):
        from fabricgate.models.platform_manifest import Attestation

        with pytest.raises(ValidationError):
            Attestation(
                bundle="cosign.bundle",
                transparency_log_url="http://rekor.sigstore.dev",
            )

    def test_url_max_length(self):
        from fabricgate.models.platform_manifest import Attestation

        with pytest.raises(ValidationError):
            Attestation(
                bundle="cosign.bundle",
                transparency_log_url="https://" + "x" * 505,
            )


# ---------------------------------------------------------------------------
# PR fields on manifests (MODEL-PR-001)
# ---------------------------------------------------------------------------


class TestManifestPRFields:
    """MODEL-PR-001: PR fields and shell_dependency consistency validator."""

    def test_pynq_standalone_default(self):
        m = PynqManifest.model_validate(_pynq_manifest_data())
        assert m.bitstream_type is None
        assert m.shell_dependency is None
        assert m.tool_requirements == []
        assert m.attestation is None
        assert m.dependencies == []

    def test_pynq_shell_type(self):
        data = _pynq_manifest_data()
        data["bitstream_type"] = "shell"
        m = PynqManifest.model_validate(data)
        assert m.bitstream_type == "shell"

    def test_pynq_partial_with_shell_dep(self):
        data = _pynq_manifest_data()
        data["bitstream_type"] = "partial"
        data["shell_dependency"] = {
            "name": "acme/shell",
            "version": "=1.0.0",
            "sha256": "ab" * 32,
        }
        m = PynqManifest.model_validate(data)
        assert m.bitstream_type == "partial"
        assert m.shell_dependency is not None

    def test_pynq_partial_without_shell_dep_rejected(self):
        data = _pynq_manifest_data()
        data["bitstream_type"] = "partial"
        with pytest.raises(ValidationError, match="shell_dependency is required"):
            PynqManifest.model_validate(data)

    def test_pynq_non_partial_with_shell_dep_rejected(self):
        data = _pynq_manifest_data()
        data["shell_dependency"] = {
            "name": "acme/shell",
            "version": "=1.0.0",
            "sha256": "ab" * 32,
        }
        with pytest.raises(ValidationError, match="must not be set"):
            PynqManifest.model_validate(data)

    def test_pynq_shell_type_with_shell_dep_rejected(self):
        data = _pynq_manifest_data()
        data["bitstream_type"] = "shell"
        data["shell_dependency"] = {
            "name": "acme/shell",
            "version": "=1.0.0",
            "sha256": "ab" * 32,
        }
        with pytest.raises(ValidationError, match="must not be set"):
            PynqManifest.model_validate(data)

    def test_pynq_with_tool_requirements(self):
        data = _pynq_manifest_data()
        data["tool_requirements"] = [
            {"tool": "vivado", "min_version": "2024.1"},
        ]
        m = PynqManifest.model_validate(data)
        assert len(m.tool_requirements) == 1
        assert m.tool_requirements[0].tool == "vivado"

    def test_pynq_with_attestation(self):
        data = _pynq_manifest_data()
        data["attestation"] = {
            "bundle": "cosign.bundle",
            "transparency_log_url": "https://rekor.sigstore.dev",
        }
        m = PynqManifest.model_validate(data)
        assert m.attestation is not None

    def test_pynq_with_dependencies(self):
        data = _pynq_manifest_data()
        data["dependencies"] = [
            {"name": "acme/core", "version": "^1.0.0"},
        ]
        m = PynqManifest.model_validate(data)
        assert len(m.dependencies) == 1

    def test_pynq_dependencies_max_20_accepted(self):
        """Exactly 20 dependencies are accepted."""
        data = _pynq_manifest_data()
        data["dependencies"] = [{"name": f"acme/dep-{i}", "version": "^1.0.0"} for i in range(20)]
        m = PynqManifest.model_validate(data)
        assert len(m.dependencies) == 20

    def test_pynq_dependencies_over_20_rejected(self):
        """More than 20 dependencies are rejected."""
        data = _pynq_manifest_data()
        data["dependencies"] = [{"name": f"acme/dep-{i}", "version": "^1.0.0"} for i in range(21)]
        with pytest.raises(ValidationError):
            PynqManifest.model_validate(data)

    def test_linux_dependencies_max_20_accepted(self):
        """LinuxFpgamgrManifest also enforces max 20 dependencies."""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bit", "sha256": "ee" * 32}},
            "dependencies": [{"name": f"acme/dep-{i}", "version": "*"} for i in range(20)],
        }
        m = LinuxFpgamgrManifest.model_validate(data)
        assert len(m.dependencies) == 20

    def test_linux_dependencies_over_20_rejected(self):
        """LinuxFpgamgrManifest rejects > 20 dependencies."""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bit", "sha256": "ee" * 32}},
            "dependencies": [{"name": f"acme/dep-{i}", "version": "*"} for i in range(21)],
        }
        with pytest.raises(ValidationError):
            LinuxFpgamgrManifest.model_validate(data)

    def test_nanopynq_dependencies_max_20_accepted(self):
        """NanopynqManifest accepts exactly 20 dependencies."""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bin", "sha256": "ff" * 32}},
            "transport": "spi",
            "mtu": 256,
            "dependencies": [{"name": f"acme/dep-{i}", "version": "*"} for i in range(20)],
        }
        m = NanopynqManifest.model_validate(data)
        assert len(m.dependencies) == 20

    def test_nanopynq_dependencies_over_20_rejected(self):
        """NanopynqManifest rejects > 20 dependencies."""
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bin", "sha256": "ff" * 32}},
            "transport": "spi",
            "mtu": 256,
            "dependencies": [{"name": f"acme/dep-{i}", "version": "*"} for i in range(21)],
        }
        with pytest.raises(ValidationError):
            NanopynqManifest.model_validate(data)

    def test_pynq_dependencies_with_optional_and_platform(self):
        """Dependencies with all fields (platform, optional) are accepted."""
        data = _pynq_manifest_data()
        data["dependencies"] = [
            {
                "name": "xilinx/axi-dma",
                "version": "^1.2.0",
                "platform": "xczu7ev/pynq",
                "optional": True,
            },
            {"name": "acme/core", "version": "^1.0.0"},
        ]
        m = PynqManifest.model_validate(data)
        assert len(m.dependencies) == 2
        assert m.dependencies[0].platform == "xczu7ev/pynq"
        assert m.dependencies[0].optional is True
        assert m.dependencies[1].optional is False

    def test_linux_partial_consistency(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {
                    "file": "blink.bit",
                    "sha256": "ee" * 32,
                },
            },
            "bitstream_type": "partial",
            "shell_dependency": {"name": "acme/shell", "version": "=1.0.0", "sha256": "ab" * 32},
        }
        m = LinuxFpgamgrManifest.model_validate(data)
        assert m.bitstream_type == "partial"

    def test_linux_partial_without_shell_dep_rejected(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "linux-fpgamgr",
            "board": "zcu104",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {
                "bitstream": {"file": "blink.bit", "sha256": "ee" * 32},
            },
            "bitstream_type": "partial",
        }
        with pytest.raises(ValidationError, match="shell_dependency is required"):
            LinuxFpgamgrManifest.model_validate(data)

    def test_nanopynq_partial_consistency(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bin", "sha256": "22" * 32}},
            "transport": "spi",
            "mtu": 1024,
            "bitstream_type": "partial",
            "shell_dependency": {"name": "acme/shell", "version": "=2.0.0", "sha256": "ab" * 32},
        }
        m = NanopynqManifest.model_validate(data)
        assert m.bitstream_type == "partial"

    def test_nanopynq_partial_without_shell_dep_rejected(self):
        data = {
            "schema": "fabricgate-platform/v1",
            "runtime": "nanopynq",
            "board": "pico-ice",
            "design_ref": "fabricgate/blink:1.0.0",
            "artifacts": {"bitstream": {"file": "blink.bin", "sha256": "22" * 32}},
            "transport": "spi",
            "mtu": 1024,
            "bitstream_type": "partial",
        }
        with pytest.raises(ValidationError, match="shell_dependency is required"):
            NanopynqManifest.model_validate(data)

    def test_invalid_bitstream_type_rejected(self):
        data = _pynq_manifest_data()
        data["bitstream_type"] = "invalid"
        with pytest.raises(ValidationError):
            PynqManifest.model_validate(data)


# ---------------------------------------------------------------------------
# SearchParams / DesignSummary bitstream_type (MODEL-PR-001)
# ---------------------------------------------------------------------------


class TestSearchParamsBitstreamType:
    """MODEL-PR-001: bitstream_type filter on SearchParams."""

    def test_default_none(self):
        from fabricgate.models.api.requests import SearchParams

        sp = SearchParams()
        assert sp.bitstream_type is None

    @pytest.mark.parametrize("bt", ["shell", "partial", "standalone"])
    def test_valid_values(self, bt: str):
        from fabricgate.models.api.requests import SearchParams

        sp = SearchParams(bitstream_type=bt)
        assert sp.bitstream_type == bt

    @pytest.mark.parametrize("bt", ["invalid", "SHELL", "Partial"])
    def test_invalid_value_rejected(self, bt: str):
        from fabricgate.models.api.requests import SearchParams

        with pytest.raises(ValidationError):
            SearchParams(bitstream_type=bt)


class TestDesignSummaryBitstreamType:
    """MODEL-PR-001: bitstream_type field on DesignSummary."""

    def test_default_none(self):
        from fabricgate.models.api.responses import DesignSummary

        ds = DesignSummary(
            name="acme/blink",
            latest_version="1.0.0",
            platforms=["xczu7ev/pynq"],
            tags=[],
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert ds.bitstream_type is None

    def test_with_bitstream_type(self):
        from fabricgate.models.api.responses import DesignSummary

        ds = DesignSummary(
            name="acme/blink",
            latest_version="1.0.0",
            platforms=["xczu7ev/pynq"],
            tags=[],
            bitstream_type="partial",
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert ds.bitstream_type == "partial"


# ---------------------------------------------------------------------------
# MODEL-DEPRECATE-001: deprecated / deprecation_message / successor fields
# ---------------------------------------------------------------------------


class TestVersionSummaryDeprecated:
    """MODEL-DEPRECATE-001: deprecated fields on VersionSummary."""

    def test_defaults(self):
        from fabricgate.models.api.responses import VersionSummary

        vs = VersionSummary(
            version="1.0.0",
            platforms=["xczu7ev/pynq"],
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert vs.deprecated is False
        assert vs.deprecation_message is None
        assert vs.successor is None

    def test_deprecated_with_message_and_successor(self):
        from fabricgate.models.api.responses import VersionSummary

        vs = VersionSummary(
            version="1.0.0",
            platforms=["xczu7ev/pynq"],
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            deprecated=True,
            deprecation_message="Use v2 instead",
            successor="acme/blink:2.0.0",
        )
        assert vs.deprecated is True
        assert vs.deprecation_message == "Use v2 instead"
        assert vs.successor == "acme/blink:2.0.0"


class TestVersionDetailResponseDeprecated:
    """MODEL-DEPRECATE-001: deprecated fields on VersionDetailResponse."""

    def test_defaults(self):
        from fabricgate.models.api.responses import VersionDetailResponse

        vdr = VersionDetailResponse(
            name="acme/blink",
            version="1.0.0",
            platforms=[],
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert vdr.deprecated is False
        assert vdr.deprecation_message is None
        assert vdr.successor is None

    def test_deprecated_with_all_fields(self):
        from fabricgate.models.api.responses import VersionDetailResponse

        vdr = VersionDetailResponse(
            name="acme/blink",
            version="1.0.0",
            platforms=[],
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            deprecated=True,
            deprecation_message="Replaced by improved design",
            successor="acme/blink-v2:1.0.0",
            yanked=False,
        )
        assert vdr.deprecated is True
        assert vdr.deprecation_message == "Replaced by improved design"
        assert vdr.successor == "acme/blink-v2:1.0.0"


class TestDeprecateResponse:
    """MODEL-DEPRECATE-001: DeprecateResponse model."""

    def test_minimal(self):
        from fabricgate.models.api.responses import DeprecateResponse

        dr = DeprecateResponse(
            name="acme/blink",
            version="1.0.0",
            deprecated=True,
        )
        assert dr.deprecated is True
        assert dr.deprecation_message is None
        assert dr.successor is None

    def test_with_message_and_successor(self):
        from fabricgate.models.api.responses import DeprecateResponse

        dr = DeprecateResponse(
            name="acme/blink",
            version="1.0.0",
            deprecated=True,
            deprecation_message="Migrated to v2",
            successor="acme/blink:2.0.0",
        )
        assert dr.deprecation_message == "Migrated to v2"
        assert dr.successor == "acme/blink:2.0.0"

    def test_undeprecate(self):
        from fabricgate.models.api.responses import DeprecateResponse

        dr = DeprecateResponse(
            name="acme/blink",
            version="1.0.0",
            deprecated=False,
        )
        assert dr.deprecated is False


# ---------------------------------------------------------------------------
# board_db.py (MODEL-BOARD-001)
# ---------------------------------------------------------------------------


class TestBoardInterface:
    def test_defaults(self):
        from fabricgate.models.board_db import BoardInterface

        iface = BoardInterface(type="pmod")
        assert iface.type == "pmod"
        assert iface.direction is None
        assert iface.count == 1
        assert iface.source == "manual"

    def test_full_fields(self):
        from fabricgate.models.board_db import BoardInterface

        iface = BoardInterface(type="hdmi", direction="tx", count=2, source="vivado-boardstore")
        assert iface.direction == "tx"
        assert iface.count == 2

    def test_extra_fields_ignored(self):
        from fabricgate.models.board_db import BoardInterface

        iface = BoardInterface(type="uart", unknown_field="x")
        assert iface.type == "uart"


class TestBoardEntry:
    def _zcu104(self, **kwargs):
        from fabricgate.models.board_db import BoardEntry

        base = dict(
            board_id="zcu104",
            display_name="Xilinx ZCU104",
            device_family="xczu7ev",
        )
        base.update(kwargs)
        return BoardEntry(**base)

    def test_minimal(self):
        entry = self._zcu104()
        assert entry.board_id == "zcu104"
        assert entry.pynq_supported is False
        assert entry.virtual is False
        assert entry.category is None
        assert entry.interfaces == []

    def test_full_fields(self):
        entry = self._zcu104(
            vendor="xilinx",
            boardpart="xilinx.com:zcu104:part0:1.1",
            device="xczu7ev-ffvc1156-2-e",
            pynq_supported=True,
        )
        assert entry.vendor == "xilinx"
        assert entry.boardpart == "xilinx.com:zcu104:part0:1.1"
        assert entry.pynq_supported is True

    def test_virtual_generic(self):
        from fabricgate.models.board_db import BoardEntry

        entry = BoardEntry(
            board_id="generic-xczu7ev",
            display_name="Generic xczu7ev",
            device_family="xczu7ev",
            virtual=True,
            category="generic",
        )
        assert entry.virtual is True
        assert entry.category == "generic"

    def test_virtual_custom(self):
        from fabricgate.models.board_db import BoardEntry

        entry = BoardEntry(
            board_id="custom-xczu7ev-ffvc1156",
            display_name="Custom xczu7ev-ffvc1156",
            device_family="xczu7ev",
            virtual=True,
            category="custom",
        )
        assert entry.category == "custom"

    def test_invalid_board_id_uppercase(self):
        from fabricgate.models.board_db import BoardEntry

        with pytest.raises(ValidationError):
            BoardEntry(board_id="ZCU104", display_name="x", device_family="xczu7ev")

    def test_invalid_board_id_leading_hyphen(self):
        from fabricgate.models.board_db import BoardEntry

        with pytest.raises(ValidationError):
            BoardEntry(board_id="-zcu104", display_name="x", device_family="xczu7ev")

    def test_invalid_category(self):
        from fabricgate.models.board_db import BoardEntry

        with pytest.raises(ValidationError):
            BoardEntry(
                board_id="generic-xczu7ev",
                display_name="x",
                device_family="xczu7ev",
                virtual=True,
                category="official",  # invalid
            )

    def test_virtual_requires_category(self):
        """VIRTUAL_CATEGORY_REQUIRED: virtual=True かつ category=None は不正."""
        from fabricgate.models.board_db import BoardEntry

        with pytest.raises(ValidationError, match="category"):
            BoardEntry(
                board_id="generic-xczu7ev",
                display_name="x",
                device_family="xczu7ev",
                virtual=True,
                # category omitted → None
            )

    def test_generic_no_boardpart(self):
        """GENERIC_NO_BOARDPART: category=generic のエントリに boardpart は不可."""
        from fabricgate.models.board_db import BoardEntry

        with pytest.raises(ValidationError, match="boardpart"):
            BoardEntry(
                board_id="generic-xczu7ev",
                display_name="x",
                device_family="xczu7ev",
                virtual=True,
                category="generic",
                boardpart="xilinx.com:bad:part0:1.0",  # forbidden
            )


class TestBoardDb:
    """Tests for BoardDb.load(), lookup(), and lookup_by_boardpart()."""

    _OFFICIAL_YAML = """\
version: fabricgate-boarddb/v1
boards:
  - board_id: zcu104
    display_name: Xilinx ZCU104
    vendor: xilinx
    boardpart: "xilinx.com:zcu104:part0:1.1"
    device: xczu7ev-ffvc1156-2-e
    device_family: xczu7ev
    pynq_supported: true
  - board_id: pynq-z2
    display_name: TUL PYNQ-Z2
    vendor: tul
    boardpart: "tul.com.tw:pynq-z2:part0:1.0"
    device: xc7z020clg400-1
    device_family: xc7z020
    pynq_supported: true
"""

    _CUSTOM_YAML = """\
version: fabricgate-boarddb/v1
boards:
  - board_id: my-custom-board
    display_name: My Custom Board
    device_family: xczu7ev
  - board_id: zcu104
    display_name: ZCU104 (User Override)
    device_family: xczu7ev
"""

    @pytest.fixture()
    def official_yaml(self, tmp_path):
        p = tmp_path / "official.yaml"
        p.write_text(self._OFFICIAL_YAML)
        return p

    @pytest.fixture()
    def custom_yaml(self, tmp_path):
        p = tmp_path / "custom.yaml"
        p.write_text(self._CUSTOM_YAML)
        return p

    def test_load_official_only(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nonexistent.yaml")
        assert len(db.boards) == 2
        assert db.lookup("zcu104") is not None
        assert db.lookup("pynq-z2") is not None

    def test_load_custom_only(self, tmp_path, custom_yaml):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=tmp_path / "nonexistent.yaml", custom_path=custom_yaml)
        assert len(db.boards) == 2
        assert db.lookup("my-custom-board") is not None

    def test_load_both_custom_overrides(self, official_yaml, custom_yaml):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=custom_yaml)
        # official has 2 entries; custom has 2 entries, one overrides zcu104
        assert len(db.boards) == 3  # pynq-z2 + zcu104(custom) + my-custom-board

        zcu = db.lookup("zcu104")
        assert zcu is not None
        assert zcu.display_name == "ZCU104 (User Override)"  # custom wins

    def test_load_missing_both(self, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(
            official_path=tmp_path / "nope1.yaml",
            custom_path=tmp_path / "nope2.yaml",
        )
        assert db.boards == []

    def test_lookup_found(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nope.yaml")
        entry = db.lookup("pynq-z2")
        assert entry is not None
        assert entry.vendor == "tul"

    def test_lookup_not_found(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nope.yaml")
        assert db.lookup("unknown-board") is None

    def test_lookup_by_boardpart_found(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nope.yaml")
        entry = db.lookup_by_boardpart("xilinx.com:zcu104:part0:1.1")
        assert entry is not None
        assert entry.board_id == "zcu104"

    def test_lookup_by_boardpart_not_found(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nope.yaml")
        assert db.lookup_by_boardpart("unknown:boardpart:99") is None

    def test_boards_property_returns_copy(self, official_yaml, tmp_path):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(official_path=official_yaml, custom_path=tmp_path / "nope.yaml")
        boards = db.boards
        boards.clear()
        assert len(db.boards) == 2  # original unaffected


class TestBoardDbSchema:
    """SCH-BOARD-001: YAML schema validation and bundled official.yaml."""

    def test_bundled_official_yaml_loads(self):
        """BoardDb.load() with no args loads bundled official.yaml."""
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(custom_path=Path("/nonexistent/custom.yaml"))
        ids = [b.board_id for b in db.boards]
        assert "zcu104" in ids
        assert "pynq-z2" in ids
        assert "pico-ice" in ids

    def test_bundled_official_has_virtual_boards(self):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(custom_path=Path("/nonexistent/custom.yaml"))
        generic = db.lookup("generic-xczu7ev")
        assert generic is not None
        assert generic.virtual is True
        assert generic.category == "generic"

    def test_bundled_official_zcu104_fields(self):
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(custom_path=Path("/nonexistent/custom.yaml"))
        zcu = db.lookup("zcu104")
        assert zcu is not None
        assert zcu.vendor == "xilinx"
        assert zcu.boardpart == "xilinx.com:zcu104:part0:1.1"
        assert zcu.pynq_supported is True
        assert len(zcu.interfaces) == 3

    def test_schema_header_validated(self, tmp_path):
        """Invalid schema version raises ValidationError."""
        import pytest
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("version: fabricgate-boarddb/v99\nboards: []\n")
        with pytest.raises(ValidationError):
            BoardDb.load(official_path=bad_yaml, custom_path=tmp_path / "nope.yaml")

    def test_missing_device_family_raises(self, tmp_path):
        """device_family is required — missing it raises ValidationError."""
        import pytest
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: myboard\n"
            "    display_name: My Board\n"
            "    # device_family intentionally omitted\n"
        )
        with pytest.raises(ValidationError):
            BoardDb.load(official_path=bad_yaml, custom_path=tmp_path / "nope.yaml")

    def test_invalid_board_id_format_raises(self, tmp_path):
        """board_id with uppercase raises ValidationError."""
        import pytest
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: MyBoard\n"
            "    display_name: Bad\n"
            "    device_family: xczu7ev\n"
        )
        with pytest.raises(ValidationError):
            BoardDb.load(official_path=bad_yaml, custom_path=tmp_path / "nope.yaml")

    def test_virtual_without_category_raises(self, tmp_path):
        """virtual=true without category raises ValidationError."""
        import pytest
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: generic-xczu7ev\n"
            "    display_name: Bad\n"
            "    device_family: xczu7ev\n"
            "    virtual: true\n"
            "    # category intentionally omitted\n"
        )
        with pytest.raises(ValidationError):
            BoardDb.load(official_path=bad_yaml, custom_path=tmp_path / "nope.yaml")

    def test_generic_with_boardpart_raises(self, tmp_path):
        """generic category with boardpart raises ValidationError."""
        import pytest
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: generic-xczu7ev\n"
            "    display_name: Bad\n"
            "    device_family: xczu7ev\n"
            "    virtual: true\n"
            "    category: generic\n"
            "    boardpart: 'xilinx.com:zcu104:part0:1.1'\n"
        )
        with pytest.raises(ValidationError):
            BoardDb.load(official_path=bad_yaml, custom_path=tmp_path / "nope.yaml")

    def test_pico_ice_no_boardpart(self):
        """pico-ice has no boardpart (non-Vivado board)."""
        from fabricgate.models.board_db import BoardDb

        db = BoardDb.load(custom_path=Path("/nonexistent/custom.yaml"))
        pico = db.lookup("pico-ice")
        assert pico is not None
        assert pico.boardpart is None
        assert pico.device_family == "ice40up5k"

    def test_duplicate_board_id_in_file_raises(self, tmp_path):
        """DUPLICATE_BOARD_ID: same board_id in one file raises ValidationError."""
        from pydantic import ValidationError

        from fabricgate.models.board_db import BoardDb

        dup_yaml = tmp_path / "dup.yaml"
        dup_yaml.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: zcu104\n"
            "    display_name: ZCU104 A\n"
            "    device_family: xczu7ev\n"
            "  - board_id: zcu104\n"
            "    display_name: ZCU104 B\n"
            "    device_family: xczu7ev\n"
        )
        with pytest.raises(ValidationError, match="重複"):
            BoardDb.load(official_path=dup_yaml, custom_path=tmp_path / "nope.yaml")

    def test_boardpart_unique_across_files_raises(self, tmp_path):
        """BOARDPART_UNIQUE: same boardpart in official + custom raises ValueError."""
        from fabricgate.models.board_db import BoardDb

        official = tmp_path / "official.yaml"
        official.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: zcu104\n"
            "    display_name: ZCU104\n"
            "    boardpart: 'xilinx.com:zcu104:part0:1.1'\n"
            "    device_family: xczu7ev\n"
        )
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: zcu104-alt\n"
            "    display_name: ZCU104 Alt\n"
            "    boardpart: 'xilinx.com:zcu104:part0:1.1'\n"  # duplicate boardpart
            "    device_family: xczu7ev\n"
        )
        with pytest.raises(ValueError, match="boardpart"):
            BoardDb.load(official_path=official, custom_path=custom)

    def test_bundled_fallback_used_when_no_user_file(self, tmp_path, monkeypatch):
        """BoardDb.load() uses bundled official.yaml when user file absent."""
        from fabricgate.models.board_db import BoardDb

        # Ensure user official path does not exist
        monkeypatch.setattr("fabricgate.models.board_db._DEFAULT_OFFICIAL", tmp_path / "nope.yaml")
        db = BoardDb.load(custom_path=tmp_path / "nope_custom.yaml")
        # Bundled file has at least these boards
        assert db.lookup("zcu104") is not None
        assert db.lookup("pynq-z2") is not None

    def test_default_official_exists_path(self, tmp_path, monkeypatch):
        """_DEFAULT_OFFICIAL が存在するとき _parse_db_file が使われる (line 179)。"""
        from fabricgate.models.board_db import BoardDb

        official = tmp_path / "official.yaml"
        official.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: test-board\n"
            "    display_name: Test Board\n"
            "    device_family: xczu7ev\n"
        )
        monkeypatch.setattr("fabricgate.models.board_db._DEFAULT_OFFICIAL", official)
        db = BoardDb.load(custom_path=tmp_path / "nope_custom.yaml")
        assert db.lookup("test-board") is not None


def test_board_db_file_is_public() -> None:
    from fabricgate.models.board_db import BoardDbFile

    schema = BoardDbFile.model_json_schema(by_alias=True)
    assert schema["properties"]["boards"]["type"] == "array"


# ---------------------------------------------------------------------------
# fabricgate/hello seed manifest contract
# ---------------------------------------------------------------------------


class TestHelloSeedFixtures:
    """Freeze the fabricgate/hello seed content contract as fixtures.

    The external ``fabricgate-hello`` repo (owner-built, spec §2-3) must
    publish manifests matching these fixtures; these tests act as the
    spec-freeze regression for the seed content.
    """

    def test_hello_design_index_validates(self):
        content = (FIXTURES / "hello_design_index.yaml").read_text()
        idx = DesignIndex.from_yaml(content)
        assert idx.name == "fabricgate/hello"
        assert idx.version == "1.0.0"

    def test_hello_design_index_metadata_contract(self):
        idx = DesignIndex.from_yaml((FIXTURES / "hello_design_index.yaml").read_text())
        # Trust/provenance layer: license, repository must be set (spec §1)
        assert idx.license == "MIT"
        assert idx.repository is not None
        assert idx.repository.startswith("https://")
        # 1.0.0 ships generic-xc7z020/pynq only (spec 決定事項)
        assert [e.platform for e in idx.platforms] == ["generic-xc7z020/pynq"]

    def test_hello_platform_manifest_validates(self):
        content = (FIXTURES / "hello_platform_manifest.yaml").read_text()
        m = parse_platform_manifest(content)
        assert isinstance(m, PynqManifest)
        assert m.board == "generic-xc7z020"
        assert m.device_family == "xc7z020"
        assert str(m.design_ref) == "fabricgate/hello:1.0.0"

    def test_hello_platform_manifest_artifact_contract(self):
        m = parse_platform_manifest((FIXTURES / "hello_platform_manifest.yaml").read_text())
        assert isinstance(m, PynqManifest)
        # PynqArtifacts = bitstream + hwh required pair, no dtbo (spec §1)
        assert m.artifacts.bitstream is not None
        assert m.artifacts.hwh is not None
        assert m.artifacts.dtbo is None
        # AXI-only design, Vivado tool requirement recorded (spec §1)
        assert m.design_portability == "axi-only"
        assert any(t.tool == "vivado" and t.min_version for t in m.tool_requirements)


# ---------------------------------------------------------------------------
# reference shell pair (fabricgate/pynq-z2-shell + fabricgate/demo-adder)
# ---------------------------------------------------------------------------


SHA256_HEX_RE = r"^[0-9a-f]{64}$"


class TestReferenceShellFixtures:
    """Freeze the reference shell pair manifest contract as fixtures.

    The external ``fabricgate-shells`` repo (owner-built, spec §6-7) must
    publish manifests matching these fixtures. This is the first real-data
    exercise of the existing shell/partial contract (schema spec §2.5-2.7,
    ADR-009 sha256 pin) — no registry-side contract change.
    """

    def test_shell_design_index_validates(self):
        content = (FIXTURES / "pynq_z2_shell_design_index.yaml").read_text()
        idx = DesignIndex.from_yaml(content)
        assert idx.name == "fabricgate/pynq-z2-shell"
        assert idx.version == "1.0.0"
        # Trust/provenance layer: MIT license + fabricgate-shells repo (spec §1/§6)
        assert idx.license == "MIT"
        assert idx.repository == "https://github.com/harurun78/fabricgate-shells"
        # 1.0.0 ships pynq-z2/pynq only (spec 決定事項: PYNQ-Z2 単独先行)
        assert [e.platform for e in idx.platforms] == ["pynq-z2/pynq"]
        # A shell is not a partial: index entries carry no shell_dependency
        assert all(e.shell_dependency is None for e in idx.platforms)

    def test_shell_platform_manifest_validates(self):
        content = (FIXTURES / "pynq_z2_shell_platform_manifest.yaml").read_text()
        m = parse_platform_manifest(content)
        assert isinstance(m, PynqManifest)
        assert m.board == "pynq-z2"
        assert m.device_family == "xc7z020"
        assert str(m.design_ref) == "fabricgate/pynq-z2-shell:1.0.0"
        # Schema §2.6 positive example: shell carries no shell_dependency
        assert m.bitstream_type == "shell"
        assert m.shell_dependency is None
        # PynqArtifacts full bitstream + hwh (spec §1)
        assert m.artifacts.bitstream is not None
        assert m.artifacts.hwh is not None
        # Vivado build version recorded (spec §1: stricter than hello)
        assert any(t.tool == "vivado" and t.min_version for t in m.tool_requirements)

    def test_demo_adder_design_index_pins_shell(self):
        import re

        idx = DesignIndex.from_yaml((FIXTURES / "demo_adder_design_index.yaml").read_text())
        assert idx.name == "fabricgate/demo-adder"
        assert idx.version == "1.0.0"
        assert idx.license == "MIT"
        assert idx.repository == "https://github.com/harurun78/fabricgate-shells"
        assert [e.platform for e in idx.platforms] == ["pynq-z2/pynq"]
        # ADR-009 pin on the index platform entry
        sd = idx.platforms[0].shell_dependency
        assert sd is not None
        assert sd.name == "fabricgate/pynq-z2-shell"
        assert sd.version == "=1.0.0"
        assert sd.sha256 is not None
        assert re.fullmatch(SHA256_HEX_RE, sd.sha256)

    def test_demo_adder_platform_manifest_validates(self):
        import re

        content = (FIXTURES / "demo_adder_platform_manifest.yaml").read_text()
        m = parse_platform_manifest(content)
        assert isinstance(m, PynqManifest)
        assert str(m.design_ref) == "fabricgate/demo-adder:1.0.0"
        # Schema §2.6: partial requires shell_dependency with exact-match pin
        assert m.bitstream_type == "partial"
        assert m.shell_dependency is not None
        assert m.shell_dependency.name == "fabricgate/pynq-z2-shell"
        assert m.shell_dependency.version == "=1.0.0"
        assert m.shell_dependency.sha256 is not None
        assert re.fullmatch(SHA256_HEX_RE, m.shell_dependency.sha256)
        # spec §1: tool_requirements mandatory for the reference partial
        assert len(m.tool_requirements) >= 1
        assert any(t.tool == "vivado" and t.min_version for t in m.tool_requirements)

    def test_demo_adder_pin_matches_shell_bitstream_digest(self):
        """ADR-009: the pin sha256 is the shell's distributed bitstream digest."""
        shell = parse_platform_manifest((FIXTURES / "pynq_z2_shell_platform_manifest.yaml").read_text())
        partial = parse_platform_manifest((FIXTURES / "demo_adder_platform_manifest.yaml").read_text())
        idx = DesignIndex.from_yaml((FIXTURES / "demo_adder_design_index.yaml").read_text())
        assert isinstance(shell, PynqManifest)
        assert isinstance(partial, PynqManifest)
        assert partial.shell_dependency is not None
        assert partial.shell_dependency.sha256 == shell.artifacts.bitstream.sha256
        idx_sd = idx.platforms[0].shell_dependency
        assert idx_sd is not None
        assert idx_sd.sha256 == shell.artifacts.bitstream.sha256

    def test_demo_adder_bitstream_digest_differs_from_shell(self):
        """Negative control against fixture digest copy-paste mistakes.

        The pin sha256 must equal the shell's distributed bitstream digest
        (ADR-009, asserted above), but the partial's *own* bitstream digest is
        a different artifact and must not collide with it in the fixtures.
        """
        shell = parse_platform_manifest((FIXTURES / "pynq_z2_shell_platform_manifest.yaml").read_text())
        partial = parse_platform_manifest((FIXTURES / "demo_adder_platform_manifest.yaml").read_text())
        assert isinstance(shell, PynqManifest)
        assert isinstance(partial, PynqManifest)
        assert partial.artifacts.bitstream.sha256 != shell.artifacts.bitstream.sha256

    def test_demo_adder_without_shell_dependency_rejected(self):
        """Dropping shell_dependency from the partial fixture must fail validation.

        Model-level counterpart of the SHELL_DEPENDENCY_REQUIRED publish error
        (validate_shell_dependency_consistency).
        """
        import yaml

        data = yaml.safe_load((FIXTURES / "demo_adder_platform_manifest.yaml").read_text())
        del data["shell_dependency"]
        with pytest.raises(ValidationError, match="shell_dependency is required"):
            PynqManifest.model_validate(data)
