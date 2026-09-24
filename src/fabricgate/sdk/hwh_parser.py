"""HWH (Hardware Handoff) XML parser for the fabricgate build command."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree

# VLNV keywords identifying AXI-family interfaces
_AXI_VLNV_KEYWORDS: frozenset[str] = frozenset(["aximm", "axi4lite", "axi4", "axis_rtl", "axi_stream", "axi_lite"])

# VLNV keywords identifying board-specific (non-portable) interfaces
_BOARD_SPECIFIC_VLNV_KEYWORDS: frozenset[str] = frozenset(
    ["mipi_csi2", "mipi_dsi", "hdmi", "displayport", "pcie", "lvds", "sdi", "hssio", "sfp", "aurora"]
)


class HwhParseError(Exception):
    """Raised when a .hwh file cannot be parsed."""


@dataclass
class ParsedInterface:
    """A single external interface extracted from a HWH file."""

    name: str
    vlnv: str
    protocol: str | None = None
    base_address: str | None = None

    @property
    def is_axi(self) -> bool:
        vlnv_lower = self.vlnv.lower()
        return any(kw in vlnv_lower for kw in _AXI_VLNV_KEYWORDS)

    @property
    def is_board_specific(self) -> bool:
        vlnv_lower = self.vlnv.lower()
        return any(kw in vlnv_lower for kw in _BOARD_SPECIFIC_VLNV_KEYWORDS)


@dataclass
class HwhInfo:
    """Parsed metadata from a single .hwh file."""

    boardpart: str | None
    """Vivado board part (``SYSTEMINFO/@BOARD``), e.g. ``xilinx.com:zcu104:part0:1.1``."""

    part: str | None
    """Vivado part string, e.g. ``xczu7ev-ffvc1156-2-e``.

    When read from ``<SYSTEMINFO>`` it is rebuilt as DEVICE+PACKAGE+SPEEDGRADE
    (e.g. ``xczu7evffvc1156-2``), so it may not match Vivado's canonical form
    (dashes, temperature grade). Nothing reads it today.
    """

    device_family: str | None
    """Device family extracted from *part*, e.g. ``xczu7ev``."""

    package: str | None
    """Package code extracted from *part*, e.g. ``ffvc1156``."""

    interfaces: list[ParsedInterface] = field(default_factory=list)

    @property
    def design_portability(self) -> str:
        """Auto-detect design portability from the external interfaces.

        Returns one of ``"axi-only"``, ``"board-specific"``, or
        ``"io-constrained"``.  IO-constrained detection requires XDC
        analysis and is not yet implemented; this property returns
        ``"axi-only"`` when no board-specific IP is found.
        """
        if any(iface.is_board_specific for iface in self.interfaces):
            return "board-specific"
        return "axi-only"


def _extract_device_family_and_package(part: str) -> tuple[str | None, str | None]:
    """Split a Vivado PART string into ``(device_family, package)``.

    Example: ``"xczu7ev-ffvc1156-2-e"`` → ``("xczu7ev", "ffvc1156")``
    """
    segments = part.lower().split("-")
    device_family = segments[0] if segments else None
    package = segments[1] if len(segments) >= 2 else None
    return device_family, package


def parse_hwh(path: Path) -> HwhInfo:
    """Parse a Vivado ``.hwh`` XML file and return structured metadata.

    Raises :class:`HwhParseError` if the file cannot be parsed.
    """
    try:
        tree = ElementTree.parse(path)
    except ElementTree.ParseError as exc:
        raise HwhParseError(f"Cannot parse {path}: {exc}") from exc

    root = tree.getroot()
    boardpart: str | None = root.get("BOARDPART")  # type: ignore[union-attr]
    part: str | None = root.get("PART")  # type: ignore[union-attr]

    device_family: str | None = None
    package: str | None = None
    if part:
        device_family, package = _extract_device_family_and_package(part)

    # Real Vivado exports carry board and device on <SYSTEMINFO>, not on the root:
    #   <SYSTEMINFO BOARD="tul.com.tw:pynq-z2:part0:1.0" DEVICE="7z020" PACKAGE="clg400" SPEEDGRADE="-1"/>
    sysinfo = root.find("SYSTEMINFO")  # type: ignore[union-attr]
    if sysinfo is not None:
        boardpart = sysinfo.get("BOARD") or boardpart
        device = sysinfo.get("DEVICE", "").lower()
        if device:
            # 7-series DEVICE lacks the "xc" prefix ("7z020"); UltraScale+ has it ("xczu7ev").
            device_family = device if device.startswith("xc") else f"xc{device}"
            package = sysinfo.get("PACKAGE", "").lower() or None
            part = f"{device_family}{package or ''}{sysinfo.get('SPEEDGRADE', '')}"

    interfaces: list[ParsedInterface] = []
    ext_ifaces = root.find("EXTERNALINTERFACES")  # type: ignore[union-attr]
    if ext_ifaces is not None:
        for iface_elem in ext_ifaces:
            vlnv = iface_elem.get("VLNV", "")
            name = iface_elem.get("NAME", "")

            protocol: str | None = None
            params_elem = iface_elem.find("PARAMETERS")
            if params_elem is not None:
                for param in params_elem:
                    if param.get("NAME") == "PROTOCOL":
                        protocol = param.get("VALUE")
                        break

            base_address: str | None = None
            addr_ranges = iface_elem.find("ADDRESSRANGES")
            if addr_ranges is not None:
                for addr_elem in addr_ranges:
                    raw = addr_elem.get("BASEADDRESS")
                    if raw:
                        try:
                            base_address = hex(int(raw, 0))
                        except ValueError:
                            base_address = raw
                        break

            interfaces.append(
                ParsedInterface(
                    name=name,
                    vlnv=vlnv,
                    protocol=protocol,
                    base_address=base_address,
                )
            )

    return HwhInfo(
        boardpart=boardpart,
        part=part,
        device_family=device_family,
        package=package,
        interfaces=interfaces,
    )


def find_hwh_files(directory: Path) -> list[Path]:
    """Recursively find all ``.hwh`` files under *directory*."""
    return sorted(directory.rglob("*.hwh"))
