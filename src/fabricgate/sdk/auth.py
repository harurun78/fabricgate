"""Authentication and token management SDK functions."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from fabricgate.client import auth
from fabricgate.client.registry_client import RegistryClient, RegistryError
from fabricgate.models.cli import (
    Credentials,
    LoginResult,
    TokenCreateResult,
    TokenInfo,
)
from fabricgate.sdk._helpers import ExitKind, SDKError, _registry_error_kind

# ---------------------------------------------------------------------------
# Token management helpers
# ---------------------------------------------------------------------------


def _parse_expires(expires: str | None) -> str | None:
    """Convert relative duration (e.g. ``90d``) to ISO 8601 datetime string."""
    if expires is None:
        return None

    match = re.fullmatch(r"(\d+)d", expires)
    if match:
        days = int(match.group(1))
        if days > 3650:
            raise SDKError("Expiry must not exceed 3650 days.", code=ExitKind.INVALID)
        dt = datetime.now(tz=UTC) + timedelta(days=days)
        return dt.isoformat()

    # ISO 8601 date or datetime; the registry needs an offset, so a bare one is UTC.
    try:
        dt = datetime.fromisoformat(expires)
    except ValueError:
        raise SDKError(
            f"Invalid --expires value '{expires}': use an ISO 8601 date/datetime or e.g. 90d.",
            code=ExitKind.INVALID,
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (delay-seconds or HTTP-date); ``None`` if absent or invalid."""
    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(tz=UTC)).total_seconds())


# ---------------------------------------------------------------------------
# Public auth functions
# ---------------------------------------------------------------------------


def login(
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
    poll_interval: float = 5.0,
    on_user_code: Callable[[str, str], None] | None = None,
) -> LoginResult:
    """Authenticate via the OAuth Device Authorization Grant flow.

    Parameters
    ----------
    registry:
        Base URL for the registry API.
    poll_interval:
        Seconds between token-poll requests (server may override via
        ``interval`` in the device response).
    on_user_code:
        Optional callback ``(verification_uri: str, user_code: str) -> None``
        invoked once the server returns the device code.

    Returns
    -------
    LoginResult
        Contains the registry URL and a human-readable storage label.
    """
    try:
        with RegistryClient(base_url=registry) as client:
            device_resp = client.device_authorization()

        user_code: str = device_resp["user_code"]
        verification_uri: str = device_resp.get("verification_uri_complete", device_resp["verification_uri"])
        device_code: str = device_resp["device_code"]
        interval: float = float(device_resp.get("interval", poll_interval))
        # Without expires_in (RFC 8628 requires it) assume 1800 s, the lifetime in RFC 8628 §3.2's example.
        deadline = time.monotonic() + float(device_resp.get("expires_in", 1800))

        if on_user_code is not None:
            on_user_code(verification_uri, user_code)

        # Poll for token
        with RegistryClient(base_url=registry) as client:
            wait = interval
            while True:
                time.sleep(wait)
                wait = interval
                try:
                    token_resp = client.token_exchange(
                        grant_type="urn:ietf:params:oauth:grant-type:device_code",
                        device_code=device_code,
                    )
                    break
                except RegistryError as exc:
                    error_code = ""
                    if exc.error:
                        error_code = exc.error.error.code
                    if error_code == "AUTHORIZATION_PENDING":
                        continue
                    if error_code == "SLOW_DOWN":
                        interval += 5
                        wait = interval
                        continue
                    if exc.status_code == 429:
                        # Rate-limited: honour Retry-After (never poll faster than
                        # ``interval``), but only while the device code is still valid.
                        retry_after = _retry_after_seconds(exc.retry_after)
                        wait = max(retry_after, interval) if retry_after is not None else interval
                        if time.monotonic() + wait > deadline:
                            raise SDKError(
                                f"Login polling was rate-limited by the registry (429) and the next "
                                f"attempt in {wait:.0f}s would come after the device code expires. "
                                "Run 'fabricgate login' again later.",
                                code=ExitKind.INVALID,
                            ) from exc
                        continue
                    raise

        cred = Credentials(
            registry=registry,
            token=token_resp.token,
            expires_at=token_resp.expires_at,
            scopes=token_resp.scopes,
            refresh_token=token_resp.refresh_token,
        )
        auth.save_credentials(cred)

        # Derive storage label
        hostname = urlparse(registry).hostname or registry
        try:
            import keyring

            keyring.get_password("fabricgate", "__connectivity_check__")
            storage = f"OS keychain ({hostname})"
        except Exception:
            storage = f"~/.fabricgate/credentials.json ({hostname})"

        return LoginResult(
            registry=registry,
            storage=storage,
        )
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def token_create(
    *,
    name: str,
    scopes: str | None = None,
    expires: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> TokenCreateResult:
    """Create a new API key.

    Parameters
    ----------
    name:
        Human-readable name for the key.
    scopes:
        Comma-separated scopes (e.g. ``"public:read,ns:alice:write"``).
        Defaults to ``["public:read"]``.
    expires:
        Expiry as ISO 8601 or relative (e.g. ``90d``).
    registry:
        Base URL for the registry API.
    """
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else ["public:read"]
    if not scope_list:
        raise SDKError("At least one scope is required.", code=ExitKind.INVALID)
    expires_at = _parse_expires(expires)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.create_api_key(name, scope_list, expires_at)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return TokenCreateResult(
        id=resp.id,
        name=resp.name,
        key=resp.key,
        scopes=resp.scopes,
        expires_at=resp.expires_at,
    )


def token_list(
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> list[TokenInfo]:
    """List all API keys for the current user."""
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            resp = client.list_api_keys()
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc

    return [
        TokenInfo(
            id=k.id,
            name=k.name,
            scopes=k.scopes,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
        )
        for k in resp.api_keys
    ]


def token_revoke(
    key_id: int,
    *,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> None:
    """Revoke an API key.

    Parameters
    ----------
    key_id:
        Numeric ID of the key to revoke.
    registry:
        Base URL for the registry API.
    """
    creds = auth.load_credentials(registry)
    if creds is None:
        raise SDKError("Not authenticated. Run 'fabricgate login' first.", code=ExitKind.PERMISSION)

    try:
        with RegistryClient(base_url=registry, token=creds.token) as client:
            client.delete_api_key(key_id)
    except RegistryError as exc:
        raise SDKError(str(exc), code=_registry_error_kind(exc)) from exc
