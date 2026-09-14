"""fabricgate build command — generate Platform Manifest and Design Index from a HWH file."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from fabricgate.models.board_db import BoardDb
from fabricgate.models.platform_manifest import Interface
from fabricgate.sdk.hwh_parser import HwhInfo, HwhParseError, ParsedInterface, find_hwh_files, parse_hwh

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

    Artifact hashes are placeholder values; the user must replace them
    before running ``fabricgate push``.
    """
    placeholder = "a" * 64
    data: dict[str, object] = {
        "schema": "fabricgate-platform/v1",
        "runtime": runtime,
        "board": board,
        "design_ref": design_ref,
        "artifacts": {
            "bitstream": {"file": "design.bit", "sha256": placeholder},
            "hwh": {"file": "design.hwh", "sha256": placeholder},
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
    # --- Step 1: Find HWH files ---
    click.echo("Scanning for HWH files ...")
    hwh_files = find_hwh_files(directory)
    if not hwh_files:
        click.echo(f"Error: No .hwh files found in {directory}", err=True)
        raise click.exceptions.Exit(1)
    for f in hwh_files:
        click.echo(f"  Found: {f.relative_to(directory.parent)}")

    if hwh_path_opt is not None:
        hwh_path = hwh_path_opt
    elif len(hwh_files) > 1:
        if not _stdin_is_tty():
            # Non-interactive: error — user must specify via --hwh
            names = ", ".join(f.name for f in hwh_files)
            click.echo(
                f"\nError: Multiple HWH files found ({names}). Use --hwh to specify one.",
                err=True,
            )
            raise click.exceptions.Exit(1)
        else:
            click.echo("\nMultiple HWH files found. Select one:")
            for i, f in enumerate(hwh_files):
                click.echo(f"  [{i + 1}] {f.relative_to(directory.parent)}")
            choice = click.prompt(
                "Select HWH file",
                type=click.IntRange(1, len(hwh_files)),
                default=1,
            )
            hwh_path = hwh_files[choice - 1]
    else:
        hwh_path = hwh_files[0]

    # --- Step 2: Parse HWH ---
    click.echo("\nParsing HWH ...")
    try:
        hwh_info = parse_hwh(hwh_path)
    except HwhParseError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

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

    portability = hwh_info.design_portability
    click.echo(f"  → design_portability: {portability}")

    # --- Step 3: Board DB lookup ---
    try:
        db = BoardDb.load()
    except Exception as exc:
        click.echo(f"Error: Board DB load failed: {exc}", err=True)
        # INFRA: failed to load local Board DB (ADR-008 exit-code standard).
        raise click.exceptions.Exit(4) from exc

    board_id: str
    device_family: str | None

    if hwh_info.boardpart:
        entry = db.lookup_by_boardpart(hwh_info.boardpart)
        if entry:
            click.echo(f"  → Board DB match: {entry.board_id} ({entry.display_name})")
            board_id = entry.board_id
            device_family = entry.device_family
        else:
            # Not in Board DB — propose virtual board
            click.echo("  → Board DB: not found")
            proposed_board_id, device_family = _resolve_board_id(hwh_info, db)
            if portability == "axi-only":
                click.echo(f"  → Suggest: {proposed_board_id}")
                if not click.confirm(
                    f"\n  Board '{hwh_info.boardpart}' is not in the Board DB.\n"
                    f"  Treat as {proposed_board_id} (AXI-only, any {device_family} board)?",
                    default=True,
                ):
                    click.echo("Aborted.", err=True)
                    raise click.exceptions.Exit(1)
            else:
                click.echo(f"  → Suggest: {proposed_board_id}")
                if not click.confirm(
                    f"\n  Platform will be registered as: {proposed_board_id}/<runtime>\n  Continue?",
                    default=True,
                ):
                    click.echo("Aborted.", err=True)
                    raise click.exceptions.Exit(1)
            board_id = proposed_board_id
    else:
        click.echo("  → No BOARDPART; cannot look up board")
        proposed_board_id, device_family = _resolve_board_id(hwh_info, db)
        board_id = proposed_board_id

    # --- Step 4: Interactive inputs ---
    click.echo("")

    ns_prompt = f"{namespace}/" if namespace else ""
    raw_name = click.prompt(f"Design name [{ns_prompt}]", default=f"{ns_prompt}my-design")
    design_name = raw_name.strip()

    raw_version = click.prompt("Version", default=semver or "0.1.0")
    version = raw_version.strip()

    runtime = _prompt_runtime()

    description = click.prompt("Description", default="", show_default=False).strip() or None

    raw_tags = tags or click.prompt("Tags (comma-separated, optional)", default="", show_default=False)
    tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

    # --- Step 5: Derive paths and build YAML ---
    platform_id = f"{board_id}/{runtime}"
    design_slug = design_name.split("/")[-1] if "/" in design_name else design_name
    platform_dir_name = f"{board_id}-{runtime}"

    design_ref = f"{design_name}:{version}"
    manifest_interfaces = _interfaces_to_manifest(hwh_info.interfaces)

    manifest_yaml = _make_manifest_stub(
        runtime=runtime,
        board=board_id,
        device_family=device_family,
        design_ref=design_ref,
        interfaces=manifest_interfaces,
        design_portability=portability,
    )
    index_yaml = _make_index_stub(
        design_name=design_name,
        version=version,
        summary=description,
        tags=tag_list,
        platform_id=platform_id,
    )

    # --- Step 6: Write (or preview) ---
    out_root = output_dir if output_dir is not None else Path(design_slug)
    manifest_path = out_root / platform_dir_name / "manifest.yaml"
    index_path = out_root / "fabricgate-index.yaml"

    click.echo("\nGenerated:")
    if dry_run:
        click.echo(f"  (dry-run) {index_path}")
        click.echo(f"  (dry-run) {manifest_path}")
        click.echo("\n--- fabricgate-index.yaml ---")
        click.echo(index_yaml)
        click.echo(f"--- {platform_dir_name}/manifest.yaml ---")
        click.echo(manifest_yaml)
        return

    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_yaml, encoding="utf-8")
        index_path.write_text(index_yaml, encoding="utf-8")
    except OSError as exc:
        click.echo(f"Error: Write failed: {exc}", err=True)
        raise click.exceptions.Exit(4) from exc

    click.echo(f"  {index_path}  ✓")
    click.echo(f"  {manifest_path}  ✓")
    click.echo(f"\nNote: Place bitstream files in {out_root / platform_dir_name}/ before publishing.")
    click.echo(f"Run `fabricgate push {out_root}/` to publish.")


def _prompt_runtime() -> str:
    result: str = click.prompt(
        "Runtime",
        type=click.Choice(["pynq", "linux-fpgamgr", "nanopynq"]),
        default="pynq",
    )
    return result
