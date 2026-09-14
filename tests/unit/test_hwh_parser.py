"""Unit tests for HWH parser and fabricgate build command."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from fabricgate.cli.commands.build import (
    _make_index_stub,
    _make_manifest_stub,
    _resolve_board_id,
    build_cmd,
)
from fabricgate.models.board_db import BoardDb, BoardEntry
from fabricgate.sdk.hwh_parser import (
    HwhInfo,
    HwhParseError,
    ParsedInterface,
    _extract_device_family_and_package,
    find_hwh_files,
    parse_hwh,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hwh(
    boardpart: str = "xilinx.com:zcu104:part0:1.1",
    part: str = "xczu7ev-ffvc1156-2-e",
    interfaces: str = "",
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<MODULE VLNV="xilinx.com:design:wrapper:1.0" MODTYPE="DESIGN"'
        f' BOARDPART="{boardpart}" PART="{part}">'
        f"<EXTERNALINTERFACES>{interfaces.strip()}</EXTERNALINTERFACES>"
        "</MODULE>"
    )


_AXI_LITE_IFACE = (
    '<EXTERNALINTERFACE VLNV="xilinx.com:interface:aximm_rtl:1.0" NAME="S_AXI_0">'
    "<PARAMETERS>"
    '<PARAMETER NAME="PROTOCOL" VALUE="AXI4Lite"/>'
    "</PARAMETERS>"
    "<ADDRESSRANGES>"
    '<RANGE BASEADDRESS="0x41200000" HIGHADDRESS="0x4120FFFF"/>'
    "</ADDRESSRANGES>"
    "</EXTERNALINTERFACE>"
)

_AXI_STREAM_IFACE = (
    '<EXTERNALINTERFACE VLNV="xilinx.com:interface:axis_rtl:1.0" NAME="M_AXIS_0">'
    "<PARAMETERS>"
    '<PARAMETER NAME="PROTOCOL" VALUE="AXI4Stream"/>'
    "</PARAMETERS>"
    "</EXTERNALINTERFACE>"
)

_MIPI_IFACE = '<EXTERNALINTERFACE VLNV="xilinx.com:interface:mipi_csi2_rtl:1.0" NAME="MIPI_CSI_0"/>'


# ---------------------------------------------------------------------------
# hwh_parser tests
# ---------------------------------------------------------------------------


class TestExtractDeviceFamilyAndPackage:
    def test_full_part(self) -> None:
        df, pkg = _extract_device_family_and_package("xczu7ev-ffvc1156-2-e")
        assert df == "xczu7ev"
        assert pkg == "ffvc1156"

    def test_simple_part(self) -> None:
        df, pkg = _extract_device_family_and_package("xc7z020-clg400-1")
        assert df == "xc7z020"
        assert pkg == "clg400"

    def test_single_segment(self) -> None:
        df, pkg = _extract_device_family_and_package("ice40up5k")
        assert df == "ice40up5k"
        assert pkg is None

    def test_preserves_lowercase(self) -> None:
        df, _ = _extract_device_family_and_package("XCZU7EV-ffvc1156-2-e")
        assert df == "xczu7ev"


class TestParseHwh:
    def test_parses_boardpart_and_part(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text(_make_hwh())
        info = parse_hwh(hwh)
        assert info.boardpart == "xilinx.com:zcu104:part0:1.1"
        assert info.part == "xczu7ev-ffvc1156-2-e"
        assert info.device_family == "xczu7ev"
        assert info.package == "ffvc1156"

    def test_parses_axi_interface(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text(_make_hwh(interfaces=_AXI_LITE_IFACE))
        info = parse_hwh(hwh)
        assert len(info.interfaces) == 1
        iface = info.interfaces[0]
        assert iface.name == "S_AXI_0"
        assert iface.is_axi is True
        assert iface.is_board_specific is False
        assert iface.protocol == "AXI4Lite"
        assert iface.base_address == "0x41200000"

    def test_parses_mipi_interface(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text(_make_hwh(interfaces=_MIPI_IFACE))
        info = parse_hwh(hwh)
        assert len(info.interfaces) == 1
        assert info.interfaces[0].is_board_specific is True
        assert info.interfaces[0].is_axi is False

    def test_no_boardpart(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text('<?xml version="1.0"?><MODULE VLNV="x:y:z:1.0" PART="xczu7ev-ffvc1156-2-e"/>')
        info = parse_hwh(hwh)
        assert info.boardpart is None
        assert info.device_family == "xczu7ev"

    def test_invalid_xml_raises(self, tmp_path: Path) -> None:
        hwh = tmp_path / "bad.hwh"
        hwh.write_text("<broken>")
        with pytest.raises(HwhParseError):
            parse_hwh(hwh)

    def test_no_external_interfaces(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text(
            '<?xml version="1.0"?><MODULE VLNV="x:y:z:1.0" BOARDPART="a:b:c:1.0" PART="xczu7ev-ffvc1156-2-e"/>'
        )
        info = parse_hwh(hwh)
        assert info.interfaces == []

    def test_invalid_base_address_kept_as_raw(self, tmp_path: Path) -> None:
        """Cover hwh_parser.py L128-129: non-hex BASEADDRESS is kept as raw string."""
        iface_with_bad_addr = (
            '<EXTERNALINTERFACE VLNV="xilinx.com:interface:aximm_rtl:1.0" NAME="S_AXI_0">'
            "<PARAMETERS>"
            '<PARAMETER NAME="PROTOCOL" VALUE="AXI4Lite"/>'
            "</PARAMETERS>"
            "<ADDRESSRANGES>"
            '<RANGE BASEADDRESS="not_a_hex_value" HIGHADDRESS="0x4120FFFF"/>'
            "</ADDRESSRANGES>"
            "</EXTERNALINTERFACE>"
        )
        hwh = tmp_path / "design.hwh"
        hwh.write_text(_make_hwh(interfaces=iface_with_bad_addr))
        info = parse_hwh(hwh)
        assert len(info.interfaces) == 1
        assert info.interfaces[0].base_address == "not_a_hex_value"


class TestHwhInfoDesignPortability:
    def test_axi_only(self, tmp_path: Path) -> None:
        hwh = tmp_path / "d.hwh"
        hwh.write_text(_make_hwh(interfaces=_AXI_LITE_IFACE))
        info = parse_hwh(hwh)
        assert info.design_portability == "axi-only"

    def test_board_specific(self, tmp_path: Path) -> None:
        hwh = tmp_path / "d.hwh"
        hwh.write_text(_make_hwh(interfaces=_MIPI_IFACE + _AXI_LITE_IFACE))
        info = parse_hwh(hwh)
        assert info.design_portability == "board-specific"

    def test_no_interfaces_defaults_to_axi_only(self, tmp_path: Path) -> None:
        hwh = tmp_path / "d.hwh"
        hwh.write_text(_make_hwh())
        info = parse_hwh(hwh)
        assert info.design_portability == "axi-only"


class TestFindHwhFiles:
    def test_finds_hwh_recursively(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "top.hwh").touch()
        (sub / "nested.hwh").touch()
        (sub / "other.txt").touch()
        found = find_hwh_files(tmp_path)
        assert len(found) == 2
        assert all(f.suffix == ".hwh" for f in found)

    def test_empty_directory(self, tmp_path: Path) -> None:
        assert find_hwh_files(tmp_path) == []


# ---------------------------------------------------------------------------
# Board resolution tests
# ---------------------------------------------------------------------------


def _minimal_board_db(entries: list[BoardEntry]) -> BoardDb:
    """Build a BoardDb directly from a list of entries (bypassing file I/O)."""
    db = BoardDb.__new__(BoardDb)
    db._boards = entries  # type: ignore[attr-defined]
    return db


class TestResolveBoardId:
    def test_resolves_from_board_db(self) -> None:
        entry = BoardEntry(
            board_id="zcu104",
            display_name="Xilinx ZCU104",
            boardpart="xilinx.com:zcu104:part0:1.1",
            device_family="xczu7ev",
        )
        db = _minimal_board_db([entry])
        info = HwhInfo(
            boardpart="xilinx.com:zcu104:part0:1.1",
            part="xczu7ev-ffvc1156-2-e",
            device_family="xczu7ev",
            package="ffvc1156",
        )
        board_id, df = _resolve_board_id(info, db)
        assert board_id == "zcu104"
        assert df == "xczu7ev"

    def test_generic_when_axi_only_and_not_in_db(self) -> None:
        db = _minimal_board_db([])
        info = HwhInfo(
            boardpart="unknown:vendor:part0:1.0",
            part="xczu7ev-ffvc1156-2-e",
            device_family="xczu7ev",
            package="ffvc1156",
        )
        board_id, df = _resolve_board_id(info, db)
        assert board_id == "generic-xczu7ev"
        assert df == "xczu7ev"

    def test_custom_when_board_specific_and_not_in_db(self) -> None:
        db = _minimal_board_db([])
        info = HwhInfo(
            boardpart="unknown:vendor:part0:1.0",
            part="xczu7ev-ffvc1156-2-e",
            device_family="xczu7ev",
            package="ffvc1156",
            interfaces=[ParsedInterface(name="MIPI", vlnv="xilinx.com:interface:mipi_csi2_rtl:1.0")],
        )
        board_id, df = _resolve_board_id(info, db)
        assert board_id == "custom-xczu7ev-ffvc1156"
        assert df == "xczu7ev"

    def test_no_boardpart_uses_virtual(self) -> None:
        db = _minimal_board_db([])
        info = HwhInfo(
            boardpart=None,
            part="xc7z020-clg400-1",
            device_family="xc7z020",
            package="clg400",
        )
        board_id, _ = _resolve_board_id(info, db)
        assert board_id == "generic-xc7z020"

    def test_fallback_when_no_device_family(self) -> None:
        db = _minimal_board_db([])
        info = HwhInfo(boardpart=None, part=None, device_family=None, package=None)
        board_id, df = _resolve_board_id(info, db)
        assert board_id == "generic-unknown"
        assert df is None


# ---------------------------------------------------------------------------
# Interface conversion tests
# ---------------------------------------------------------------------------


class TestInterfacesToManifest:
    def test_axi4lite_protocol(self) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        ifaces = [ParsedInterface(name="S_AXI", vlnv="xilinx.com:interface:aximm_rtl:1.0", protocol="AXI4Lite")]
        result = _interfaces_to_manifest(ifaces)
        assert result[0].type == "axi-lite"

    def test_axi4stream_protocol_not_misclassified_as_axi(self) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        ifaces = [ParsedInterface(name="M_AXIS", vlnv="xilinx.com:interface:axis_rtl:1.0", protocol="AXI4Stream")]
        result = _interfaces_to_manifest(ifaces)
        assert result[0].type == "axi-stream"

    def test_axi4_full_protocol(self) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        ifaces = [ParsedInterface(name="M_AXI", vlnv="xilinx.com:interface:aximm_rtl:1.0", protocol="AXI4")]
        result = _interfaces_to_manifest(ifaces)
        assert result[0].type == "axi"

    def test_stream_detected_from_vlnv_when_no_protocol(self) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        ifaces = [ParsedInterface(name="M_AXIS", vlnv="xilinx.com:interface:axis_rtl:1.0", protocol=None)]
        result = _interfaces_to_manifest(ifaces)
        assert result[0].type == "axi-stream"

    def test_base_address_forwarded(self) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        ifaces = [ParsedInterface(name="S_AXI", vlnv="x:y:aximm:1.0", protocol="AXI4Lite", base_address="0x41200000")]
        result = _interfaces_to_manifest(ifaces)
        assert result[0].base == "0x41200000"


# ---------------------------------------------------------------------------
# YAML generation tests
# ---------------------------------------------------------------------------


class TestMakeManifestStub:
    def test_basic_fields_present(self) -> None:
        result = _make_manifest_stub(
            runtime="pynq",
            board="zcu104",
            device_family="xczu7ev",
            design_ref="myns/blink:1.0.0",
            interfaces=[],
            design_portability="axi-only",
        )
        data = yaml.safe_load(result)
        assert data["schema"] == "fabricgate-platform/v1"
        assert data["runtime"] == "pynq"
        assert data["board"] == "zcu104"
        assert data["device_family"] == "xczu7ev"
        assert data["design_portability"] == "axi-only"
        assert data["design_ref"] == "myns/blink:1.0.0"
        assert "bitstream" in data["artifacts"]
        assert "hwh" in data["artifacts"]

    def test_no_device_family_omitted(self) -> None:
        result = _make_manifest_stub(
            runtime="pynq",
            board="generic-xczu7ev",
            device_family=None,
            design_ref="myns/blink:1.0.0",
            interfaces=[],
            design_portability="axi-only",
        )
        data = yaml.safe_load(result)
        assert "device_family" not in data

    def test_interfaces_included(self) -> None:
        from fabricgate.models.platform_manifest import Interface

        ifaces = [Interface(name="S_AXI_0", type="axi-lite", base="0x41200000")]
        result = _make_manifest_stub(
            runtime="pynq",
            board="zcu104",
            device_family="xczu7ev",
            design_ref="myns/blink:1.0.0",
            interfaces=ifaces,
            design_portability="axi-only",
        )
        data = yaml.safe_load(result)
        assert data["interfaces"][0]["name"] == "S_AXI_0"
        assert data["interfaces"][0]["base"] == "0x41200000"


class TestMakeIndexStub:
    def test_basic_fields_present(self) -> None:
        result = _make_index_stub(
            design_name="myns/blink",
            version="1.0.0",
            summary="LED blink",
            tags=["demo"],
            platform_id="zcu104/pynq",
        )
        data = yaml.safe_load(result)
        assert data["schema"] == "fabricgate-index/v1"
        assert data["name"] == "myns/blink"
        assert data["version"] == "1.0.0"
        assert data["summary"] == "LED blink"
        assert data["tags"] == ["demo"]
        assert data["platforms"][0]["platform"] == "zcu104/pynq"
        assert data["platforms"][0]["digest"].startswith("sha256:")

    def test_no_summary_omitted(self) -> None:
        result = _make_index_stub(
            design_name="myns/blink",
            version="1.0.0",
            summary=None,
            tags=[],
            platform_id="zcu104/pynq",
        )
        data = yaml.safe_load(result)
        assert "summary" not in data
        assert "tags" not in data


# ---------------------------------------------------------------------------
# CLI integration tests (using CliRunner)
# ---------------------------------------------------------------------------


class TestBuildCmd:
    def _make_hwh_file(self, directory: Path, interfaces: str = "", name: str = "design.hwh") -> Path:
        hwh = directory / name
        hwh.write_text(
            f'<?xml version="1.0"?>'
            f'<MODULE VLNV="x:y:z:1.0" BOARDPART="xilinx.com:zcu104:part0:1.1"'
            f' PART="xczu7ev-ffvc1156-2-e"><EXTERNALINTERFACES>{interfaces}</EXTERNALINTERFACES></MODULE>'
        )
        return hwh

    def _make_board_db_yaml(self, tmp_path: Path) -> Path:
        """Write a minimal board-db official.yaml."""
        db_file = tmp_path / "official.yaml"
        db_file.write_text(
            "version: fabricgate-boarddb/v1\n"
            "boards:\n"
            "  - board_id: zcu104\n"
            "    display_name: Xilinx ZCU104\n"
            "    boardpart: xilinx.com:zcu104:part0:1.1\n"
            "    device_family: xczu7ev\n"
            "    pynq_supported: true\n"
        )
        return db_file

    def test_dry_run_no_files_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        self._make_hwh_file(src)
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        runner = CliRunner()
        result = runner.invoke(
            build_cmd,
            [str(src), "--namespace", "myns", "--version", "1.0.0", "--dry-run"],
            input="myns/my-design\n1.0.0\npynq\nLED blink\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "(dry-run)" in result.output
        assert not (tmp_path / "my-design").exists()

    def test_writes_files_on_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        self._make_hwh_file(src)
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        runner = CliRunner()
        result = runner.invoke(
            build_cmd,
            [str(src), "--namespace", "myns", "--version", "1.0.0"],
            input="myns/my-design\n1.0.0\npynq\nLED blink\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "my-design" / "fabricgate-index.yaml").exists()
        assert (tmp_path / "my-design" / "zcu104-pynq" / "manifest.yaml").exists()

    def test_exit_1_when_no_hwh(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(build_cmd, [str(tmp_path)])
        assert result.exit_code == 1

    def test_exit_4_when_board_db_load_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Board DB load failure → exit 4 (INFRA, ADR-008; previously 2)."""
        src = tmp_path / "vivado"
        src.mkdir()
        self._make_hwh_file(src)
        monkeypatch.chdir(tmp_path)

        def _raise(**_kw: object) -> BoardDb:
            raise RuntimeError("corrupt board db")

        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(_raise)}),
        )

        runner = CliRunner()
        result = runner.invoke(build_cmd, [str(src), "--namespace", "myns", "--version", "1.0.0"])
        assert result.exit_code == 4
        assert "Board DB load failed" in result.output

    def test_tags_option(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        self._make_hwh_file(src)
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        runner = CliRunner()
        result = runner.invoke(
            build_cmd,
            [str(src), "--version", "0.1.0", "--tags", "dma,axi", "--dry-run"],
            input="myns/blink\n0.1.0\npynq\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "dma" in result.output

    def test_output_option_writes_to_custom_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        self._make_hwh_file(src)
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        out = tmp_path / "custom_output"
        runner = CliRunner()
        result = runner.invoke(
            build_cmd,
            [str(src), "--version", "1.0.0", "--output", str(out)],
            input="myns/my-design\n1.0.0\npynq\nLED blink\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        # Files written under custom_output/, not under <design_slug>/
        assert (out / "fabricgate-index.yaml").exists()
        assert (out / "zcu104-pynq" / "manifest.yaml").exists()
        assert not (tmp_path / "my-design").exists()

    def test_hwh_option_selects_explicit_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        hwh1 = self._make_hwh_file(src, name="design_a.hwh")
        hwh2 = src / "design_b.hwh"
        hwh2.write_text(hwh1.read_text())  # second HWH file
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        runner = CliRunner()
        result = runner.invoke(
            build_cmd,
            [str(src), "--version", "1.0.0", "--hwh", str(hwh2), "--dry-run"],
            input="myns/my-design\n1.0.0\npynq\nLED blink\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "(dry-run)" in result.output

    def test_multiple_hwh_prompts_for_selection(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "vivado"
        src.mkdir()
        hwh1 = self._make_hwh_file(src, name="design_a.hwh")
        hwh2 = src / "design_b.hwh"
        hwh2.write_text(hwh1.read_text())
        db_file = self._make_board_db_yaml(tmp_path)
        monkeypatch.chdir(tmp_path)
        real_db = BoardDb.load(official_path=db_file)
        monkeypatch.setattr(
            "fabricgate.cli.commands.build.BoardDb",
            type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: real_db)}),
        )

        # Simulate TTY so the interactive selection prompt is shown.
        monkeypatch.setattr("fabricgate.cli.commands.build._stdin_is_tty", lambda: True)

        runner = CliRunner()
        # Input: select file 1, then answer design prompts
        result = runner.invoke(
            build_cmd,
            [str(src), "--version", "1.0.0", "--dry-run"],
            input="1\nmyns/my-design\n1.0.0\npynq\nLED blink\n\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "Multiple HWH files found" in result.output
        assert "Select one:" in result.output
        assert "(dry-run)" in result.output

    def test_multiple_hwh_non_tty_errors(self, tmp_path: Path) -> None:
        """Non-TTY with multiple HWH files must exit 1 and suggest --hwh."""
        src = tmp_path / "vivado"
        src.mkdir()
        hwh1 = self._make_hwh_file(src, name="design_a.hwh")
        hwh2 = src / "design_b.hwh"
        hwh2.write_text(hwh1.read_text())

        # CliRunner uses mix_stderr=True by default, so err=True output appears in result.output.
        runner = CliRunner()
        # CliRunner stdin is not a TTY (default) — should trigger error path.
        result = runner.invoke(build_cmd, [str(src), "--version", "1.0.0"])
        assert result.exit_code == 1
        assert "Multiple HWH files found" in result.output
        assert "--hwh" in result.output
