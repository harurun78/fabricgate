"""fabricgate push command."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@dataclass
class _PlatformInfo:
    board_id: str
    runtime: str
    device_family: str | None
    design_portability: str | None


def _is_tty() -> bool:
    """Return True when stdin is an interactive terminal (monkeypatchable in tests)."""
    return sys.stdin.isatty()


def _detect_platform_info(directory: Path) -> _PlatformInfo | None:
    """Load the first platform entry from the design index and its manifest.

    Returns ``None`` if the directory does not contain a valid design index.
    """
    from pydantic import ValidationError

    from fabricgate.client.publisher import PublishError, load_design_index
    from fabricgate.models.platform_manifest import parse_platform_manifest

    try:
        index, _ = load_design_index(directory)
    except (PublishError, OSError):
        return None

    if not index.platforms:
        return None

    platform_id = str(index.platforms[0].platform)  # e.g. "custom-xczu7ev/pynq"
    if "/" not in platform_id:
        return None

    board_id, runtime = platform_id.split("/", 1)

    # Manifest lives at <project_dir>/<device>/<runtime>/manifest.yaml
    manifest_path = directory / platform_id / "manifest.yaml"
    if not manifest_path.exists():
        return _PlatformInfo(board_id=board_id, runtime=runtime, device_family=None, design_portability=None)

    try:
        manifest = parse_platform_manifest(manifest_path.read_text(encoding="utf-8"))
    except (ValidationError, OSError):
        return _PlatformInfo(board_id=board_id, runtime=runtime, device_family=None, design_portability=None)

    return _PlatformInfo(
        board_id=board_id,
        runtime=runtime,
        device_family=getattr(manifest, "device_family", None),
        design_portability=getattr(manifest, "design_portability", None),
    )


def _handle_promotion_prompt(
    board_id: str,
    device_family: str,
    runtime: str,
    *,
    yes: bool,
) -> str | None:
    """Return target board_id to promote to, or None to keep original."""
    target = f"generic-{device_family}"

    if yes:
        return target  # --yes → auto-promote

    if not _is_tty():
        click.echo(
            f"Info: design is axi-only on {board_id}; "
            f"consider promoting to {target}/{runtime} (run with --yes to auto-promote)"
        )
        return None

    # Interactive TTY: ask with default N
    if click.confirm(f"Register as {target}/{runtime} instead?", default=False):
        return target
    return None


def _parse_artifact_urls(
    _ctx: click.Context,
    _param: click.Parameter,
    values: tuple[str, ...],
) -> dict[str, str] | None:
    """Turn repeated ``<filename>=<url>`` values into a mapping (``None`` when unused)."""
    urls: dict[str, str] = {}
    for value in values:
        filename, sep, url = value.partition("=")
        if not sep or not filename or not url:
            raise click.BadParameter(f"expected <filename>=<url>, got {value!r}")
        if filename in urls:
            raise click.BadParameter(f"{filename} is given more than once")
        urls[filename] = url
    return urls or None


@click.command(name="push")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--namespace", default=None, help="Override namespace for publishing.")
@click.option(
    "--yes",
    "auto_yes",
    is_flag=True,
    default=False,
    help="Auto-promote axi-only custom-* designs to the generic-* platform.",
)
@click.option(
    "--skip-sha-check",
    is_flag=True,
    default=False,
    help="Suppress placeholder sha256 warnings (does NOT bypass verification of real hashes).",
)
@click.option(
    "--artifact-url",
    "artifact_urls",
    multiple=True,
    metavar="<filename>=<url>",
    callback=_parse_artifact_urls,
    help="Publish <filename> by reference to an existing https URL instead of uploading it. Repeatable.",
)
@click.pass_obj
def push_cmd(
    obj: dict[str, object],
    directory: Path,
    namespace: str | None,
    auto_yes: bool,
    skip_sha_check: bool,
    artifact_urls: dict[str, str] | None,
) -> None:
    """Publish a design to the registry."""
    board_override: str | None = None
    promoted_platform: str | None = None

    info = _detect_platform_info(directory)
    if info is not None:
        if auto_yes and info.design_portability != "axi-only":
            click.echo("--yes requires axi-only design", err=True)
            raise click.exceptions.Exit(1)

        if info.board_id.startswith("custom-") and info.design_portability == "axi-only":
            # Derive device_family from board_id if not in manifest
            device_family = info.device_family or info.board_id.split("-", 1)[1]
            board_override = _handle_promotion_prompt(info.board_id, device_family, info.runtime, yes=auto_yes)
            if board_override is not None:
                promoted_platform = f"{board_override}/{info.runtime}"

    try:
        result = sdk_api.push(
            directory,
            namespace=namespace,
            registry=str(obj["registry"]),
            board_override=board_override,
            skip_sha_check=skip_sha_check,
            artifact_urls=artifact_urls,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    if promoted_platform:
        click.echo(f"Pushed as {promoted_platform}")
    else:
        click.echo(f"Published: {result.name}:{result.version} ({len(result.platforms)} platforms)")
    if result.quota_warning:
        click.echo(f"  ⚠ {result.quota_warning}", err=True)
    if result.sha_warning:
        click.echo(f"  ⚠ Warning: {result.sha_warning}", err=True)
        click.echo("    Tip: compute real artifact hashes after flashing to override the placeholder.", err=True)
