"""fabricgate build command — generate Platform Manifest and Design Index from a HWH file."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from pydantic import TypeAdapter, ValidationError

from fabricgate.cli.exit_codes import exit_with
from fabricgate.client.errors import FailureKind
from fabricgate.models.board_db import BoardDb
from fabricgate.models.common import DesignName
from fabricgate.models.platform_manifest import Interface
from fabricgate.sdk.hwh_parser import HwhInfo, HwhParseError, ParsedInterface, find_hwh_files, parse_hwh

# Artifact file names the manifest stub declares, next to manifest.yaml.
_BITSTREAM_FILE = "design.bit"
_HWH_FILE = "design.hwh"

_DESIGN_NAME_ADAPTER: TypeAdapter[str] = TypeAdapter(DesignName)

# ---------------------------------------------------------------------------
# Board resolution helpers
# ---------------------------------------------------------------------------


def _stdin_is_tty() -> bool:
    """Whether interactive prompts are possible (patched in tests)."""
    return sys.stdin.isatty()


def _resolve_board_id(
    hwh_info: HwhInfo,
    db: BoardDb,
) -> tuple[str, str | None]:
    """Return ``(board_id, device_family)`` from *hwh_info* and *db*.

    Resolution order:
    1. BOARDPART lookup in Board DB.
    2. Virtual board based on *design_portability*.
    """
    if hwh_info.boardpart:
        entry = db.lookup_by_boardpart(hwh_info.boardpart)
        if entry:
            return entry.board_id, entry.device_family

    portability = hwh_info.design_portability
    df = hwh_info.device_family
    pkg = hwh_info.package

    if portability == "board-specific" and df and pkg:
        return f"custom-{df}-{pkg}", df
    if portability == "board-specific" and df:
        return f"custom-{df}", df
    # axi-only or io-constrained
    if df:
        return f"generic-{df}", df
    return "generic-unknown", None


def _interfaces_to_manifest(parsed: list[ParsedInterface]) -> list[Interface]:
    """Convert parsed HWH interfaces to manifest :class:`Interface` objects."""
    result: list[Interface] = []
    for p in parsed:
        iface_type = "axi-lite"
        if p.protocol:
            proto = p.protocol.lower()
            if "stream" in proto:
                iface_type = "axi-stream"
            elif "lite" in proto:
                iface_type = "axi-lite"
            elif "axi4" in proto:
                iface_type = "axi"
        elif "stream" in p.vlnv.lower() or "axis_rtl" in p.vlnv.lower():
            iface_type = "axi-stream"
        result.append(
            Interface(
                name=p.name,
                type=iface_type,
                base=p.base_address,
            )
        )
    return result


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------


def _make_manifest_stub(
    *,
    runtime: str,
    board: str,
    device_family: str | None,
    design_ref: str,
    interfaces: list[Interface],
    design_portability: str,
) -> str:
    """Return a YAML string for a platform manifest stub.

    Artifact hashes are placeholder values; ``fabricgate push`` replaces them
    with the hashes of the files it uploads.
    """
    placeholder = "a" * 64
    data: dict[str, object] = {
        "schema": "fabricgate-platform/v1",
        "runtime": runtime,
        "board": board,
        "design_ref": design_ref,
        "artifacts": {
            "bitstream": {"file": _BITSTREAM_FILE, "sha256": placeholder},
            "hwh": {"file": _HWH_FILE, "sha256": placeholder},
        },
    }
    if device_family:
        data["device_family"] = device_family
    data["design_portability"] = design_portability
    if interfaces:
        data["interfaces"] = [
            {k: v for k, v in {"name": i.name, "type": i.type, "base": i.base}.items() if v is not None}
            for i in interfaces
        ]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _make_index_stub(
    *,
    design_name: str,
    version: str,
    summary: str | None,
    tags: list[str],
    platform_id: str,
) -> str:
    """Return a YAML string for a design index stub."""
    placeholder = "sha256:" + "a" * 64
    data: dict[str, object] = {
        "schema": "fabricgate-index/v1",
        "name": design_name,
        "version": version,
        "platforms": [{"platform": platform_id, "digest": placeholder}],
    }
    if summary:
        data["summary"] = summary
    if tags:
        data["tags"] = tags
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _render_stubs(inputs: _BuildInputs) -> tuple[str, str]:
    """Return ``(index_yaml, manifest_yaml)`` for *inputs*."""
    manifest_yaml = _make_manifest_stub(
        runtime=inputs.runtime,
        board=inputs.board_id,
        device_family=inputs.device_family,
        design_ref=f"{inputs.design_name}:{inputs.version}",
        interfaces=_interfaces_to_manifest(inputs.hwh_info.interfaces),
        design_portability=inputs.hwh_info.design_portability,
    )
    index_yaml = _make_index_stub(
        design_name=inputs.design_name,
        version=inputs.version,
        summary=inputs.description,
        tags=inputs.tags,
        platform_id=inputs.platform_id,
    )
    return index_yaml, manifest_yaml


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command(name="build")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--namespace", default=None, help="Registry namespace (interactive if omitted).")
@click.option("--version", "semver", default=None, help="SemVer version (interactive if omitted).")
@click.option("--tags", default=None, help="Comma-separated tags (e.g. dma,axi,zynq).")
@click.option("--dry-run", is_flag=True, help="Preview output without writing files.")
@click.option(
    "--output",
    "output_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory (default: <design_slug>/ in current directory).",
)
@click.option(
    "--hwh",
    "hwh_path_opt",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Explicit path to .hwh file (required when multiple .hwh files are found).",
)
def build_cmd(
    directory: Path,
    namespace: str | None,
    semver: str | None,
    tags: str | None,
    dry_run: bool,
    output_dir: Path | None,
    hwh_path_opt: Path | None,
) -> None:
    """Generate Platform Manifest and Design Index from a Vivado HWH file."""
    inputs = _collect_inputs(directory, hwh_path_opt, namespace=namespace, semver=semver, tags=tags)
    index_yaml, manifest_yaml = _render_stubs(inputs)
    _write_outputs(inputs, index_yaml, manifest_yaml, output_dir=output_dir, dry_run=dry_run)


@dataclass(frozen=True)
class _BuildInputs:
    """What ``build`` reads from the HWH and asks the user, before generating YAML."""

    hwh_path: Path
    hwh_info: HwhInfo
    board_id: str
    device_family: str | None
    design_name: str
    version: str
    runtime: str
    description: str | None
    tags: list[str]

    @property
    def platform_id(self) -> str:
        return f"{self.board_id}/{self.runtime}"


def _collect_inputs(
    directory: Path,
    hwh_path_opt: Path | None,
    *,
    namespace: str | None,
    semver: str | None,
    tags: str | None,
) -> _BuildInputs:
    hwh_path = _select_hwh(directory, hwh_path_opt)
    hwh_info = _parse_hwh_and_report(hwh_path)
    board_id, device_family = _choose_board(hwh_info)

    # --- Interactive inputs ---
    click.echo("")

    ns_prompt = f"{namespace}/" if namespace else ""
    design_name: str = click.prompt(
        f"Design name [{ns_prompt}]",
        default=f"{ns_prompt}my-design",
        value_proc=lambda raw: _to_design_name(raw, namespace),
    )

    raw_version = click.prompt("Version", default=semver or "0.1.0")
    version = raw_version.strip()

    runtime = _prompt_runtime()

    description = click.prompt("Description", default="", show_default=False).strip() or None

    raw_tags = tags or click.prompt("Tags (comma-separated, optional)", default="", show_default=False)
    tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

    return _BuildInputs(
        hwh_path=hwh_path,
        hwh_info=hwh_info,
        board_id=board_id,
        device_family=device_family,
        design_name=design_name,
        version=version,
        runtime=runtime,
        description=description,
        tags=tag_list,
    )


def _to_design_name(raw: str, namespace: str | None) -> str:
    """Return *raw* as ``<namespace>/<design>``, asking for the namespace when *raw* has none.

    push refuses an index whose name is not a :data:`DesignName`, so build checks it here;
    raising :class:`click.BadParameter` makes ``click.prompt`` ask again.
    """
    name = raw.strip()
    if "/" not in name:
        ns = namespace or click.prompt("Namespace").strip()
        name = f"{ns}/{name}"
    try:
        return _DESIGN_NAME_ADAPTER.validate_python(name)
    except ValidationError:
        msg = f"{name!r} is not <namespace>/<design> (lowercase letters, digits and hyphens)"
        raise click.BadParameter(msg) from None


def _select_hwh(directory: Path, hwh_path_opt: Path | None) -> Path:
    click.echo("Scanning for HWH files ...")
    # An HWH next to a manifest.yaml is the copy an earlier build made, not a Vivado output.
    hwh_files = [f for f in find_hwh_files(directory) if not (f.parent / "manifest.yaml").exists()]
    if not hwh_files:
        click.echo(f"Error: No .hwh files found in {directory}", err=True)
        exit_with(FailureKind.GENERIC)
    for f in hwh_files:
        click.echo(f"  Found: {f.relative_to(directory.parent)}")

    if hwh_path_opt is not None:
        return hwh_path_opt
    if len(hwh_files) > 1:
        if not _stdin_is_tty():
            # Non-interactive: error — user must specify via --hwh
            names = ", ".join(f.name for f in hwh_files)
            click.echo(
                f"\nError: Multiple HWH files found ({names}). Use --hwh to specify one.",
                err=True,
            )
            exit_with(FailureKind.GENERIC)
        click.echo("\nMultiple HWH files found. Select one:")
        for i, f in enumerate(hwh_files):
            click.echo(f"  [{i + 1}] {f.relative_to(directory.parent)}")
        choice = click.prompt(
            "Select HWH file",
            type=click.IntRange(1, len(hwh_files)),
            default=1,
        )
        return hwh_files[choice - 1]
    return hwh_files[0]


def _parse_hwh_and_report(hwh_path: Path) -> HwhInfo:
    click.echo("\nParsing HWH ...")
    try:
        hwh_info = parse_hwh(hwh_path)
    except HwhParseError as exc:
        click.echo(f"Error: {exc}", err=True)
        exit_with(FailureKind.GENERIC)

    if hwh_info.boardpart:
        click.echo(f"  BOARDPART: {hwh_info.boardpart}")
    else:
        click.echo("  BOARDPART: (not found)")
    if hwh_info.interfaces:
        axi_count = sum(1 for i in hwh_info.interfaces if i.is_axi)
        bs_count = sum(1 for i in hwh_info.interfaces if i.is_board_specific)
        iface_summary = f"{len(hwh_info.interfaces)} interface(s)"
        if axi_count:
            iface_summary += f", {axi_count} AXI"
        if bs_count:
            bs_names = [i.vlnv.split(":")[-2] for i in hwh_info.interfaces if i.is_board_specific]
            iface_summary += f", board-specific: {', '.join(bs_names)}"
        click.echo(f"  EXTERNALINTERFACES: {iface_summary}")
    else:
        click.echo("  EXTERNALINTERFACES: (none)")

    click.echo(f"  → design_portability: {hwh_info.design_portability}")
    return hwh_info


def _choose_board(hwh_info: HwhInfo) -> tuple[str, str | None]:
    """Return ``(board_id, device_family)``, asking before using a board that is not in the Board DB."""
    try:
        db = BoardDb.load()
    except Exception as exc:
        click.echo(f"Error: Board DB load failed: {exc}", err=True)
        # INFRA: failed to load local Board DB (ADR-008 exit-code standard).
        exit_with(FailureKind.INFRA)

    if not hwh_info.boardpart:
        click.echo("  → No BOARDPART; cannot look up board")
        return _resolve_board_id(hwh_info, db)

    entry = db.lookup_by_boardpart(hwh_info.boardpart)
    if entry:
        click.echo(f"  → Board DB match: {entry.board_id} ({entry.display_name})")
        return entry.board_id, entry.device_family

    # Not in Board DB — propose virtual board
    click.echo("  → Board DB: not found")
    proposed_board_id, device_family = _resolve_board_id(hwh_info, db)
    if hwh_info.design_portability == "axi-only":
        click.echo(f"  → Suggest: {proposed_board_id}")
        if not click.confirm(
            f"\n  Board '{hwh_info.boardpart}' is not in the Board DB.\n"
            f"  Treat as {proposed_board_id} (AXI-only, any {device_family} board)?",
            default=True,
        ):
            click.echo("Aborted.", err=True)
            exit_with(FailureKind.GENERIC)
    else:
        click.echo(f"  → Suggest: {proposed_board_id}")
        if not click.confirm(
            f"\n  Platform will be registered as: {proposed_board_id}/<runtime>\n  Continue?",
            default=True,
        ):
            click.echo("Aborted.", err=True)
            exit_with(FailureKind.GENERIC)
    return proposed_board_id, device_family


def _write_outputs(
    inputs: _BuildInputs,
    index_yaml: str,
    manifest_yaml: str,
    *,
    output_dir: Path | None,
    dry_run: bool,
) -> None:
    design_slug = inputs.design_name.split("/")[-1] if "/" in inputs.design_name else inputs.design_name
    out_root = output_dir if output_dir is not None else Path(design_slug)
    # push reads <project>/<board_id>/<runtime>/manifest.yaml
    manifest_path = out_root / inputs.board_id / inputs.runtime / "manifest.yaml"
    index_path = out_root / "fabricgate-index.yaml"
    hwh_path = manifest_path.parent / _HWH_FILE

    click.echo("\nGenerated:")
    if dry_run:
        click.echo(f"  (dry-run) {index_path}")
        click.echo(f"  (dry-run) {manifest_path}")
        click.echo(f"  (dry-run) {hwh_path}")
        click.echo("\n--- fabricgate-index.yaml ---")
        click.echo(index_yaml)
        click.echo(f"--- {inputs.platform_id}/manifest.yaml ---")
        click.echo(manifest_yaml)
        return

    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_yaml, encoding="utf-8")
        # push uploads the HWH from next to the manifest, under the name the manifest declares.
        if inputs.hwh_path.resolve() != hwh_path.resolve():
            shutil.copyfile(inputs.hwh_path, hwh_path)
        index_path.write_text(index_yaml, encoding="utf-8")
    except OSError as exc:
        click.echo(f"Error: Write failed: {exc}", err=True)
        exit_with(FailureKind.INFRA)

    click.echo(f"  {index_path}  ✓")
    click.echo(f"  {manifest_path}  ✓")
    click.echo(f"  {hwh_path}  ✓")
    click.echo(f"\nNote: Copy the bitstream to {manifest_path.parent / _BITSTREAM_FILE} before publishing.")
    click.echo(f"Run `fabricgate push {out_root}/` to publish.")


def _prompt_runtime() -> str:
    result: str = click.prompt(
        "Runtime",
        type=click.Choice(["pynq", "linux-fpgamgr", "nanopynq"]),
        default="pynq",
    )
    return result
