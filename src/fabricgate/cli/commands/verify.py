"""fabricgate verify command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from fabricgate.cli.exit_codes import exit_with, sdk_errors
from fabricgate.client.errors import FailureKind
from fabricgate.sdk import api as sdk_api


@click.command(name="verify")
@click.argument("directory", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option("--ref", default=None, help="Expected version (<namespace>/<design>:<version>). Default: the manifest's.")
@click.option(
    "--platform", "expected_platform", default=None, help="Expected registry platform (<board_id>/<runtime>)."
)
@click.option("--offline", is_flag=True, default=False, help="Check only the artifacts, not the manifest.")
@click.pass_obj
def verify_cmd(
    obj: dict[str, object], directory: Path, ref: str | None, expected_platform: str | None, offline: bool
) -> None:
    """Verify a pulled design directory against the registry and its manifest."""
    # Not the global --platform (FG_PLATFORM): a pull that fell back to a generic-*
    # platform would then fail here.
    with sdk_errors():
        result = sdk_api.verify(
            directory, ref=ref, platform=expected_platform, offline=offline, registry=str(obj["registry"])
        )

    if result.yanked:
        reason = f": {result.yanked_reason}" if result.yanked_reason else ""
        click.echo(f"⚠ {result.checked_ref} is yanked{reason}", err=True)

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        if not all(artifact.verified for artifact in result.artifacts):
            exit_with(FailureKind.INVALID)
        return

    click.echo(f"Verifying {result.design_ref} ({result.platform}) ...")
    if result.manifest_verified:
        source = "" if ref is not None else " (version from the manifest's design_ref; pin it with --ref)"
        click.echo(f"  manifest matches {result.checked_ref} ({result.checked_platform}){source}")
    else:
        click.echo("  manifest not checked against the registry (--offline)")
    failed = False
    for artifact in result.artifacts:
        status = "OK" if artifact.verified else "FAIL"
        click.echo(f"  {artifact.file} sha256:{artifact.sha256} {status}")
        failed = failed or not artifact.verified

    if failed:
        exit_with(FailureKind.INVALID)
    click.echo("All artifacts verified.")
