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
    """Verify a pulled design directory, its dependencies and shell, against the registry and their manifests."""
    # Not the global --platform (FG_PLATFORM): a pull that fell back to a generic-*
    # platform would then fail here.
    with sdk_errors():
        result = sdk_api.verify(
            directory, ref=ref, platform=expected_platform, offline=offline, registry=str(obj["registry"])
        )

    checked = [
        ("", result),
        *(("dependency ", d) for d in result.dependencies),
        *(("shell ", d) for d in result.shells),
    ]
    for _, item in checked:
        if item.yanked:
            reason = f": {item.yanked_reason}" if item.yanked_reason else ""
            click.echo(f"⚠ {item.checked_ref} is yanked{reason}", err=True)
    failed = not all(artifact.verified for _, item in checked for artifact in item.artifacts)

    if obj["json"]:
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        if failed:
            exit_with(FailureKind.INVALID)
        return

    for kind, item in checked:
        click.echo(f"Verifying {kind}{item.design_ref} ({item.platform}) ...")
        if item.manifest_verified:
            # Only the root's version can come from its own manifest; the others come from their paths.
            source = "" if kind or ref is not None else " (version from the manifest's design_ref; pin it with --ref)"
            click.echo(f"  manifest matches {item.checked_ref} ({item.checked_platform}){source}")
        else:
            click.echo("  manifest not checked against the registry (--offline)")
        for artifact in item.artifacts:
            status = "OK" if artifact.verified else "FAIL"
            click.echo(f"  {artifact.file} sha256:{artifact.sha256} {status}")
    for name in result.missing:
        click.echo(f"Not pulled, not checked: {name}")

    if failed:
        exit_with(FailureKind.INVALID)
    click.echo("All artifacts verified.")
