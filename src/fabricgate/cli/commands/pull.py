"""fabricgate pull command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_code_for
from fabricgate.sdk import api as sdk_api


@click.command(name="pull")
@click.argument("design_ref")
@click.option("--platform", default=None, help="Target platform.")
@click.option("--output", type=click.Path(path_type=Path, file_okay=False), default=None, help="Output directory.")
@click.option("--verify/--no-verify", "verify_digests", default=True, help="Verify artifact digests after download.")
@click.option("--no-deps", is_flag=True, default=False, help="Skip dependency resolution.")
@click.option("--deps-only", is_flag=True, default=False, help="Download dependencies only, skip root design.")
@click.option("--include-optional-deps", is_flag=True, default=False, help="Include optional dependencies.")
@click.option("--no-shell", is_flag=True, default=False, help="Skip shell auto-download for partial bitstreams.")
@click.option("--verify-attestation", is_flag=True, default=False, help="Verify cosign attestation for artifacts.")
@click.pass_obj
def pull_cmd(
    obj: dict[str, object],
    design_ref: str,
    platform: str | None,
    output: Path | None,
    verify_digests: bool,
    no_deps: bool,
    deps_only: bool,
    include_optional_deps: bool,
    no_shell: bool,
    verify_attestation: bool,
) -> None:
    """Download a design for a specific platform."""
    effective_platform: str | None = (
        platform if platform is not None else (str(obj["platform"]) if obj["platform"] else None)
    )

    if no_shell:
        click.echo("\u26a0  Shell dependency skipped. Ensure shell bitstream is present before loading.", err=True)

    try:
        result = sdk_api.pull(
            design_ref,
            platform=effective_platform,
            output=output,
            verify_digests=verify_digests,
            registry=str(obj["registry"]),
            cache_dir=Path(str(obj["cache_dir"])),
            no_deps=no_deps,
            deps_only=deps_only,
            include_optional_deps=include_optional_deps,
            no_shell=no_shell,
            verify_attestation=verify_attestation,
        )
    except sdk_api.SDKError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(exit_code_for(exc)) from exc

    if result.deprecated_warning:
        click.echo(f"\u26a0  {result.deprecated_warning}", err=True)

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    if result.fallback_from:
        click.echo(f"Selected: {result.platform} (family fallback from {result.fallback_from})")
    click.echo(f"Saved to {result.path}")
    for artifact in result.artifacts:
        click.echo(f"  {artifact}")
    if result.dependencies:
        click.echo("Dependencies:")
        for dep in result.dependencies:
            click.echo(f"  {dep}")
    if result.shell:
        click.echo(f"Shell: {result.shell}")
