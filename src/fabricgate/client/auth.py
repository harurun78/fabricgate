"""Credentials read/write.

Prefers OS keychain via ``keyring``; falls back to
``~/.fabricgate/credentials.json`` (mode 0600). ``FABRICGATE_TOKEN``
overrides both when reading (CLI spec §3.8).
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from fabricgate.models.cli import Credentials

_log = logging.getLogger(__name__)

_DEFAULT_CRED_PATH = Path.home() / ".fabricgate" / "credentials.json"
_KEYRING_SERVICE = "fabricgate"
TOKEN_ENV = "FABRICGATE_TOKEN"


def _try_keyring_load(registry: str) -> Credentials | None:
    try:
        import keyring

        raw = keyring.get_password(_KEYRING_SERVICE, registry)
        if raw:
            return Credentials.model_validate_json(raw)
    except Exception:
        _log.debug("keyring unavailable, falling back to file")
    return None


def _try_keyring_save(cred: Credentials) -> bool:
    try:
        import keyring

        keyring.set_password(
            _KEYRING_SERVICE,
            cred.registry,
            cred.model_dump_json(),
        )
        return True
    except Exception:
        _log.debug("keyring unavailable, falling back to file")
    return False


def _try_keyring_delete(registry: str) -> bool:
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, registry)
        return True
    except Exception:
        pass
    return False


# ---- File-based fallback ----


def _load_creds_file(path: Path) -> dict[str, Credentials]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: Credentials.model_validate_json(json.dumps(v)) for k, v in data.items()}


def _save_creds_file(creds: dict[str, Credentials], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: v.model_dump(mode="json") for k, v in creds.items()}, indent=2),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


# ---- Public API ----


def load_credentials(registry: str, path: Path | None = None) -> Credentials | None:
    """Load credentials for *registry*.

    A non-empty ``FABRICGATE_TOKEN`` (an API key or any bearer token) wins over
    the stored credentials. Its scopes and expiry are known only to the
    registry, so ``scopes`` is empty and ``expires_at`` is a placeholder.
    """
    if token := os.getenv(TOKEN_ENV):
        return Credentials(
            registry=registry,
            token=token,
            expires_at=datetime.max.replace(tzinfo=UTC),
            scopes=[],
        )
    cred = _try_keyring_load(registry)
    if cred is not None:
        return cred
    creds = _load_creds_file(path or _DEFAULT_CRED_PATH)
    return creds.get(registry)


def save_credentials(cred: Credentials, path: Path | None = None) -> None:
    """Persist credentials for *cred.registry*."""
    if _try_keyring_save(cred):
        return
    file_path = path or _DEFAULT_CRED_PATH
    creds = _load_creds_file(file_path)
    creds[cred.registry] = cred
    _save_creds_file(creds, file_path)


def delete_credentials(registry: str, path: Path | None = None) -> None:
    """Remove credentials for *registry*."""
    if _try_keyring_delete(registry):
        return
    file_path = path or _DEFAULT_CRED_PATH
    creds = _load_creds_file(file_path)
    creds.pop(registry, None)
    _save_creds_file(creds, file_path)
