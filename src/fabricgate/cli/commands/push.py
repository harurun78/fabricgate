"""fabricgate push command."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_with, sdk_errors
from fabricgate.client.errors import FailureKind
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


def _detect_platforms(directory: Path) -> list[_PlatformInfo]:
    """Load every platform entry from the design index together with its manifest.

    Returns an empty list if the directory does not contain a valid design index.
    """
    from pydantic import ValidationError

    from fabricgate.client.publisher import PublishError, load_design_index
    from fabricgate.models.platform_manifest import parse_platform_manifest

    try:
        index, _ = load_design_index(directory)
    except (PublishError, OSError):
        return []

    infos: list[_PlatformInfo] = []
    for entry in index.platforms:
        platform_id = str(entry.platform)  # e.g. "custom-xczu7ev-ffvc1156/pynq"
        if "/" not in platform_id:
            continue
        board_id, runtime = platform_id.split("/", 1)
        info = _PlatformInfo(board_id=board_id, runtime=runtime, device_family=None, design_portability=None)
        # Manifest lives at <project_dir>/<board_id>/<runtime>/manifest.yaml
        manifest_path = directory / platform_id / "manifest.yaml"
        if manifest_path.exists():
            try:
                manifest = parse_platform_manifest(manifest_path.read_text(encoding="utf-8"))
            except (ValidationError, OSError):
                pass
            else:
                info.device_family = getattr(manifest, "device_family", None)
                info.design_portability = getattr(manifest, "design_portability", None)
        infos.append(info)
    return infos


def _family_from_custom_board(board_id: str) -> str:
    """``custom-{device_family}-{package}`` (or ``custom-{device_family}``) → device family."""
    rest = board_id.removeprefix("custom-")
    return rest.rsplit("-", 1)[0] if "-" in rest else rest


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
            f"consider promoting to {target}/{runtime} (run with --yes to auto-promote)",
            err=True,  # stdout carries the --json result
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
    hidden=True,  # No effect since push fills in placeholder sha256 values; kept so scripts keep working.
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

    infos = _detect_platforms(directory)
    # The SDK promotes every custom-* platform, so promotion is offered only when all
    # of them are axi-only and share one device family.
    custom = [info for info in infos if info.board_id.startswith("custom-")]
    families = {info.device_family or _family_from_custom_board(info.board_id) for info in custom}
    promotable = bool(custom) and all(info.design_portability == "axi-only" for info in custom)
    if auto_yes and infos and not (promotable or all(info.design_portability == "axi-only" for info in infos)):
        click.echo("--yes requires axi-only design", err=True)
        exit_with(FailureKind.GENERIC)
    if promotable and len(families) > 1:
        if auto_yes:
            click.echo("--yes cannot promote custom-* platforms of different device families", err=True)
            exit_with(FailureKind.GENERIC)
        promotable = False
    if promotable:
        (family,) = families
        targets = [f"generic-{family}/{info.runtime}" for info in custom]
        existing = {f"{info.board_id}/{info.runtime}" for info in infos if not info.board_id.startswith("custom-")}
        if len(set(targets)) < len(targets) or existing & set(targets):
            if auto_yes:
                click.echo("--yes cannot promote: two platforms would share one generic-* platform", err=True)
                exit_with(FailureKind.GENERIC)
            promotable = False

    if promotable:
        (device_family,) = families
        board_label = ", ".join(info.board_id for info in custom)
        runtime_label = ", ".join(info.runtime for info in custom)
        board_override = _handle_promotion_prompt(board_label, device_family, runtime_label, yes=auto_yes)
        if board_override is not None:
            promoted_platform = ", ".join(f"{board_override}/{info.runtime}" for info in custom)

    with sdk_errors():
        result = sdk_api.push(
            directory,
            namespace=namespace,
            registry=str(obj["registry"]),
            board_override=board_override,
            skip_sha_check=skip_sha_check,
            artifact_urls=artifact_urls,
        )

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
