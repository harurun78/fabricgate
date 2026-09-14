"""Client configuration (config file + env var merge)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from fabricgate.models.cli import RegistryConfig

_DEFAULT_CONFIG_DIR = Path.home() / ".fabricgate"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.yaml"


def _env_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    if registry := os.getenv("FG_REGISTRY"):
        overrides["registry"] = registry
    if platform := os.getenv("FG_PLATFORM"):
        overrides["platform"] = platform
    if cache_dir := os.getenv("FG_CACHE_DIR"):
        overrides["cache_dir"] = cache_dir
    return overrides


def load_config(path: Path | None = None) -> RegistryConfig:
    """Load client config from *path*, falling back to defaults.

    Environment variables (``FG_REGISTRY``, ``FG_PLATFORM``, ``FG_CACHE_DIR``)
    override file values when set.
    """
    config_path = path or _DEFAULT_CONFIG_FILE
    data: dict[str, object] = {}
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text) or {}
        if isinstance(loaded, dict):
            data = loaded
    data.update(_env_overrides())
    return RegistryConfig.model_validate(data)


def save_config(config: RegistryConfig, path: Path | None = None) -> None:
    """Persist *config* to YAML."""
    config_path = path or _DEFAULT_CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(exclude_none=True)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
