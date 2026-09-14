"""Client logic for FabricGate registry interaction."""

from fabricgate.client.auth import delete_credentials, load_credentials, save_credentials
from fabricgate.client.cache import load_index, lookup, platform_dir, save_index, store
from fabricgate.client.config import load_config, save_config
from fabricgate.client.errors import FailureKind
from fabricgate.client.publisher import PublishError, collect_artifacts, load_design_index, load_platform_manifest
from fabricgate.client.registry_client import RegistryClient, RegistryClientProtocol, RegistryError
from fabricgate.client.resolver import (
    PlatformResolution,
    ResolutionError,
    resolve_platform,
    resolve_platform_detailed,
)
from fabricgate.client.validator import sha256_digest, sha256_hex, verify_artifact, verify_digest

__all__ = [
    "FailureKind",
    "PlatformResolution",
    "PublishError",
    "RegistryClient",
    "RegistryClientProtocol",
    "RegistryError",
    "ResolutionError",
    "collect_artifacts",
    "delete_credentials",
    "load_config",
    "load_credentials",
    "load_design_index",
    "load_index",
    "load_platform_manifest",
    "lookup",
    "platform_dir",
    "resolve_platform",
    "resolve_platform_detailed",
    "save_config",
    "save_credentials",
    "save_index",
    "sha256_digest",
    "sha256_hex",
    "store",
    "verify_artifact",
    "verify_digest",
]
