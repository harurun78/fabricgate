"""fabricgate — FabricGate CLI entry point (alias: fgate)."""

from __future__ import annotations

from pathlib import Path

import click

from fabricgate import __version__
from fabricgate.cli.commands.build import build_cmd
from fabricgate.cli.commands.deprecate import deprecate_cmd
from fabricgate.cli.commands.diff import diff_cmd
from fabricgate.cli.commands.info import info_cmd
from fabricgate.cli.commands.license_check import license_check_cmd
from fabricgate.cli.commands.list_cmd import list_cmd
from fabricgate.cli.commands.login import login_cmd
from fabricgate.cli.commands.pull import pull_cmd
from fabricgate.cli.commands.push import push_cmd
from fabricgate.cli.commands.quota import quota_cmd
from fabricgate.cli.commands.search import search_cmd
from fabricgate.cli.commands.stats import stats_cmd
from fabricgate.cli.commands.token import token_group
from fabricgate.cli.commands.verify import verify_cmd
from fabricgate.cli.commands.watch import watch_cmd
from fabricgate.cli.commands.webhook import webhook_group
from fabricgate.cli.commands.yank import yank_cmd
from fabricgate.client.config import load_config


@click.group()
@click.option("--registry", envvar="FG_REGISTRY", default=None, help="Registry base URL.")
@click.option("--platform", envvar="FG_PLATFORM", default=None, help="Default target platform.")
@click.option(
    "--cache-dir",
    envvar="FG_CACHE_DIR",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Local cache directory.",
)
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.version_option(version=__version__, prog_name="fabricgate")
@click.pass_context
def main(
    ctx: click.Context,
    registry: str | None,
    platform: str | None,
    cache_dir: Path | None,
    verbose: bool,
    json_output: bool,
) -> None:
    """FabricGate — FPGA design registry CLI."""
    config = load_config()
    ctx.obj = {
        "registry": registry or config.registry,
        "platform": platform or config.platform,
        "cache_dir": cache_dir or Path(config.cache_dir).expanduser(),
        "verbose": verbose,
        "json": json_output,
    }


main.add_command(build_cmd)
main.add_command(search_cmd)
main.add_command(stats_cmd)
main.add_command(list_cmd)
main.add_command(info_cmd)
main.add_command(pull_cmd)
main.add_command(verify_cmd)
main.add_command(login_cmd)
main.add_command(push_cmd)
main.add_command(quota_cmd)
main.add_command(token_group)
main.add_command(webhook_group)
main.add_command(yank_cmd)
main.add_command(deprecate_cmd)
main.add_command(license_check_cmd)
main.add_command(diff_cmd)
main.add_command(watch_cmd)


if __name__ == "__main__":
    main()
