"""Unit tests for HWH parser and fabricgate build command."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner, Result

from fabricgate.cli.commands.build import (
    _make_index_stub,
    _make_manifest_stub,
    _resolve_board_id,
    build_cmd,
)
from fabricgate.client.publisher import collect_artifacts, load_design_index
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

    def test_parses_real_vivado_systeminfo(self, tmp_path: Path) -> None:
        # Shape of a real Vivado export: no root BOARDPART/PART, board and device under SYSTEMINFO.
        hwh = tmp_path / "design.hwh"
        hwh.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<EDKSYSTEM EDWVERSION="1.2" TIMESTAMP="Thu Jan  1 00:00:00 2023" VIVADOVERSION="2022.1">'
            '<SYSTEMINFO ARCH="zynq" BOARD="tul.com.tw:pynq-z2:part0:1.0" DEVICE="7z020"'
            ' NAME="dma_axis_ip_example" PACKAGE="clg400" SPEEDGRADE="-1"/>'
            "</EDKSYSTEM>"
        )
        info = parse_hwh(hwh)
        assert info.boardpart == "tul.com.tw:pynq-z2:part0:1.0"
        assert info.part == "xc7z020clg400-1"
        assert info.device_family == "xc7z020"
        assert info.package == "clg400"

    def test_systeminfo_ultrascale_device_keeps_xc_prefix(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text(
            '<?xml version="1.0"?><EDKSYSTEM>'
            '<SYSTEMINFO ARCH="zynquplus" BOARD="xilinx.com:zcu104:part0:1.1" DEVICE="xczu7ev"'
            ' PACKAGE="ffvc1156" SPEEDGRADE="-2"/>'
            "</EDKSYSTEM>"
        )
        info = parse_hwh(hwh)
        assert info.boardpart == "xilinx.com:zcu104:part0:1.1"
        assert info.device_family == "xczu7ev"
        assert info.package == "ffvc1156"

    def test_neither_systeminfo_nor_root_attributes(self, tmp_path: Path) -> None:
        hwh = tmp_path / "design.hwh"
        hwh.write_text('<?xml version="1.0"?><EDKSYSTEM VIVADOVERSION="2022.1"/>')
        info = parse_hwh(hwh)
        assert info.boardpart is None
        assert info.part is None
        assert info.device_family is None
        assert info.package is None

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

    def test_custom_without_package_when_board_specific(self) -> None:
        db = _minimal_board_db([])
        info = HwhInfo(
            boardpart="unknown:vendor:part0:1.0",
            part=None,
            device_family="xczu7ev",
            package=None,
            interfaces=[ParsedInterface(name="MIPI", vlnv="xilinx.com:interface:mipi_csi2_rtl:1.0")],
        )
        board_id, df = _resolve_board_id(info, db)
        assert board_id == "custom-xczu7ev"
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

    @pytest.mark.parametrize(
        ("vlnv", "protocol"),
        [("xilinx.com:interface:apb_rtl:1.0", "APB4"), ("xilinx.com:interface:aximm_rtl:1.0", None)],
        ids=["unknown-protocol", "no-protocol-not-stream"],
    )
    def test_falls_back_to_axi_lite(self, vlnv: str, protocol: str | None) -> None:
        from fabricgate.cli.commands.build import _interfaces_to_manifest

        result = _interfaces_to_manifest([ParsedInterface(name="S", vlnv=vlnv, protocol=protocol)])
        assert result[0].type == "axi-lite"

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
        assert (tmp_path / "my-design" / "zcu104" / "pynq" / "manifest.yaml").exists()

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
        assert (out / "zcu104" / "pynq" / "manifest.yaml").exists()
        assert not (tmp_path / "my-design").exists()
        # The layout is the one push reads: <project>/<platform>/manifest.yaml for every index entry (#65).
        index, _ = load_design_index(out)
        assert all((out / str(entry.platform) / "manifest.yaml").exists() for entry in index.platforms)

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


_BUILD_INPUT = "myns/my-design\n1.0.0\npynq\nLED blink\n\n"
_UNKNOWN_BOARDPART = "acme.com:board:part0:1.0"
_AXI_IFACE = ParsedInterface(name="S_AXI", vlnv="xilinx.com:interface:aximm_rtl:1.0", protocol="AXI4LITE")
_HDMI_IFACE = ParsedInterface(name="hdmi_out", vlnv="digilentinc.com:interface:hdmi_rtl:1.0")


def _invoke_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    info: HwhInfo,
    args: list[str],
    stdin: str,
) -> Result:
    """Run ``build`` with *info* as the parsed HWH and a Board DB that only knows the ZCU104."""
    src = tmp_path / "vivado"
    src.mkdir()
    (src / "design.hwh").write_text("<unused/>")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("fabricgate.cli.commands.build.parse_hwh", lambda _path: info)
    db = _minimal_board_db(
        [
            BoardEntry(
                board_id="zcu104",
                display_name="Xilinx ZCU104",
                boardpart="xilinx.com:zcu104:part0:1.1",
                device_family="xczu7ev",
            )
        ]
    )
    monkeypatch.setattr(
        "fabricgate.cli.commands.build.BoardDb",
        type("FakeBoardDb", (object,), {"load": staticmethod(lambda **_kw: db)}),
    )
    return CliRunner().invoke(build_cmd, [str(src), *args], input=stdin)


class TestBuildCmdBoardResolution:
    """Branches of ``build`` that the HWH fixtures above do not reach (#110)."""

    @pytest.mark.parametrize(
        ("interfaces", "board_id", "question"),
        [
            ([_AXI_IFACE], "generic-xc7z020", "Treat as generic-xc7z020 (AXI-only, any xc7z020 board)?"),
            ([_AXI_IFACE, _HDMI_IFACE], "custom-xc7z020-clg400", "registered as: custom-xc7z020-clg400/<runtime>"),
        ],
        ids=["axi-only", "board-specific"],
    )
    def test_unknown_board_accepted_by_default_uses_the_virtual_board(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        interfaces: list[ParsedInterface],
        board_id: str,
        question: str,
    ) -> None:
        info = HwhInfo(_UNKNOWN_BOARDPART, "xc7z020clg400-1", "xc7z020", "clg400", list(interfaces))
        # Enter alone answers the confirmation: the default is yes.
        result = _invoke_build(tmp_path, monkeypatch, info, [], "\n" + _BUILD_INPUT)

        assert result.exit_code == 0, result.output
        assert "→ Board DB: not found" in result.output
        assert f"→ Suggest: {board_id}" in result.output
        assert question in result.output
        manifest = yaml.safe_load((tmp_path / "my-design" / board_id / "pynq" / "manifest.yaml").read_text())
        assert manifest["board"] == board_id
        assert manifest["device_family"] == "xc7z020"

    @pytest.mark.parametrize(
        "interfaces", [[_AXI_IFACE], [_AXI_IFACE, _HDMI_IFACE]], ids=["axi-only", "board-specific"]
    )
    def test_unknown_board_declined_aborts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interfaces: list[ParsedInterface]
    ) -> None:
        info = HwhInfo(_UNKNOWN_BOARDPART, "xc7z020clg400-1", "xc7z020", "clg400", list(interfaces))
        result = _invoke_build(tmp_path, monkeypatch, info, [], "n\n" + _BUILD_INPUT)

        assert result.exit_code == 1
        assert "Aborted." in result.output
        assert "Design name" not in result.output
        assert not (tmp_path / "my-design").exists()

    @pytest.mark.parametrize(
        ("interfaces", "summary"),
        [
            ([_AXI_IFACE, _HDMI_IFACE], "2 interface(s), 1 AXI, board-specific: hdmi_rtl"),
            ([_HDMI_IFACE], "1 interface(s), board-specific: hdmi_rtl"),
        ],
        ids=["axi-and-hdmi", "hdmi-only"],
    )
    def test_reports_the_interface_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interfaces: list[ParsedInterface], summary: str
    ) -> None:
        info = HwhInfo(_UNKNOWN_BOARDPART, "xc7z020clg400-1", "xc7z020", "clg400", list(interfaces))
        result = _invoke_build(tmp_path, monkeypatch, info, ["--dry-run"], "y\n" + _BUILD_INPUT)

        assert result.exit_code == 0, result.output
        assert f"EXTERNALINTERFACES: {summary}\n" in result.output
        assert "design_portability: board-specific" in result.output

    def test_no_boardpart_uses_the_virtual_board_without_asking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = HwhInfo(None, "xc7z020clg400-1", "xc7z020", "clg400")
        result = _invoke_build(tmp_path, monkeypatch, info, [], _BUILD_INPUT)

        assert result.exit_code == 0, result.output
        assert "BOARDPART: (not found)" in result.output
        assert "EXTERNALINTERFACES: (none)" in result.output
        assert "→ No BOARDPART; cannot look up board" in result.output
        assert "Continue?" not in result.output
        assert (tmp_path / "my-design" / "generic-xc7z020" / "pynq" / "manifest.yaml").exists()

    def test_parse_error_exits_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_path: Path) -> HwhInfo:
            raise HwhParseError("broken hwh")

        src = tmp_path / "vivado"
        src.mkdir()
        (src / "design.hwh").write_text("<unused/>")
        monkeypatch.setattr("fabricgate.cli.commands.build.parse_hwh", _raise)

        result = CliRunner().invoke(build_cmd, [str(src)], input=_BUILD_INPUT)

        assert result.exit_code == 1
        assert "Error: broken hwh" in result.output

    def test_write_failure_exits_4(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A file where the board directory must go makes mkdir fail (INFRA)."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "zcu104").write_text("not a directory")
        info = HwhInfo("xilinx.com:zcu104:part0:1.1", "xczu7ev-ffvc1156-2-e", "xczu7ev", "ffvc1156")
        result = _invoke_build(tmp_path, monkeypatch, info, ["--output", str(out)], _BUILD_INPUT)

        assert result.exit_code == 4
        assert "Error: Write failed" in result.output
        assert not (out / "fabricgate-index.yaml").exists()


_ZCU104_INFO = HwhInfo("xilinx.com:zcu104:part0:1.1", "xczu7ev-ffvc1156-2-e", "xczu7ev", "ffvc1156")


class TestBuildOutputIsPushable:
    """#143: ``build`` then placing the bitstream is enough for ``push``."""

    def test_push_collects_the_build_output_with_real_hashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, [], _BUILD_INPUT)
        assert result.exit_code == 0, result.output
        out = tmp_path / "my-design"
        platform_dir = out / "zcu104" / "pynq"
        bit_path = platform_dir / "design.bit"
        assert f"Copy the bitstream to {bit_path.relative_to(tmp_path)}" in result.output
        # The HWH that build parsed sits next to the manifest under the declared name.
        assert (platform_dir / "design.hwh").read_text() == "<unused/>"
        bit_path.write_bytes(b"bitstream")

        index, _ = load_design_index(out)
        files = collect_artifacts(out, index)

        # What the registry checks: each upload against the manifest, the manifest against the index.
        manifest = files["platform:zcu104/pynq:manifest"]
        artifacts = yaml.safe_load(manifest)["artifacts"]
        for ref in artifacts.values():
            content = files[f"platform:zcu104/pynq:artifact:{ref['file']}"]
            assert ref["sha256"] == hashlib.sha256(content).hexdigest()
        (entry,) = yaml.safe_load(files["index"])["platforms"]
        assert entry["digest"] == f"sha256:{hashlib.sha256(manifest).hexdigest()}"

    def test_dry_run_does_not_copy_the_hwh(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, ["--dry-run"], _BUILD_INPUT)
        assert result.exit_code == 0, result.output
        assert "(dry-run) my-design/zcu104/pynq/design.hwh" in result.output
        assert not (tmp_path / "my-design").exists()

    def test_hwh_already_in_place_is_kept(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Building again from the HWH build copied must not fail on copying it onto itself."""
        assert _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, [], _BUILD_INPUT).exit_code == 0
        copied = tmp_path / "my-design" / "zcu104" / "pynq" / "design.hwh"
        # The patches from the first run are still active.
        result = CliRunner().invoke(build_cmd, [str(tmp_path / "vivado"), "--hwh", str(copied)], input=_BUILD_INPUT)
        assert result.exit_code == 0, result.output
        assert copied.read_text() == "<unused/>"

    def test_rebuild_ignores_the_hwh_an_earlier_build_copied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Building again with the output inside the scanned folder finds only the Vivado HWH."""
        out = tmp_path / "vivado" / "out"
        assert _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, ["--output", str(out)], _BUILD_INPUT).exit_code == 0
        assert (out / "zcu104" / "pynq" / "design.hwh").exists()
        # Not a TTY: two HWH files would be an error.
        result = CliRunner().invoke(build_cmd, [str(tmp_path / "vivado"), "--output", str(out)], input=_BUILD_INPUT)
        assert result.exit_code == 0, result.output
        assert "Found: vivado/design.hwh\n" in result.output
        assert "out/zcu104" not in result.output.split("Parsing HWH")[0]

    @pytest.mark.parametrize(
        ("args", "stdin", "expected"),
        [
            ([], "blink\nmyns\n1.0.0\npynq\n\n\n", "myns/blink"),  # asks for the namespace
            ([], "\nmyns\n1.0.0\npynq\n\n\n", "myns/my-design"),  # the default has no namespace
            (["--namespace", "myns"], "blink\n1.0.0\npynq\n\n\n", "myns/blink"),
            (["--namespace", "myns"], "other/blink\n1.0.0\npynq\n\n\n", "other/blink"),
        ],
        ids=["no-namespace", "default", "namespace-option", "typed-namespace-wins"],
    )
    def test_design_name_gets_a_namespace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], stdin: str, expected: str
    ) -> None:
        result = _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, [*args, "--output", "out"], stdin)
        assert result.exit_code == 0, result.output
        index, _ = load_design_index(tmp_path / "out")
        assert str(index.name) == expected

    def test_invalid_design_name_is_asked_again(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        stdin = "MyNS/My_Design\nmyns/my-design\n1.0.0\npynq\n\n\n"
        result = _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, [], stdin)
        assert result.exit_code == 0, result.output
        assert "'MyNS/My_Design' is not <namespace>/<design>" in result.output
        index, _ = load_design_index(tmp_path / "my-design")
        assert str(index.name) == "myns/my-design"

    def test_input_ending_without_a_valid_design_name_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _invoke_build(tmp_path, monkeypatch, _ZCU104_INFO, [], "Not Valid/x\n")
        assert result.exit_code == 1
        assert not (tmp_path / "my-design").exists()


def test_parse_hwh_refuses_entities_as_a_parse_error(tmp_path: Path) -> None:
    """#69: defusedxml's refusal and a missing file surface as HwhParseError, which build reports."""
    hwh = tmp_path / "evil.hwh"
    hwh.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><EDKSYSTEM>&e;</EDKSYSTEM>')
    with pytest.raises(HwhParseError):
        parse_hwh(hwh)
    with pytest.raises(HwhParseError):
        parse_hwh(tmp_path / "missing.hwh")
