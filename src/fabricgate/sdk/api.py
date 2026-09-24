"""Public SDK API functions.

This module is a thin re-export shim.  All implementations live in the
domain submodules:
- sdk/_helpers.py  — shared helpers and SDKError
- sdk/auth.py      — login, token_create, token_list, token_revoke
- sdk/webhooks.py  — webhook_create, webhook_list, webhook_delete, webhook_test, webhook_deliveries
- sdk/designs.py   — search, list_remote, info, push, pull, verify, yank, deprecate, undeprecate,
                      diff, quota, stats, license_check, watch
"""

from __future__ import annotations

from fabricgate.client import auth  # re-exported so sdk_api.auth resolves for test patches
from fabricgate.sdk._helpers import ExitKind, FailureKind, SDKError
from fabricgate.sdk.auth import (
    login,
    token_create,
    token_list,
    token_revoke,
)
from fabricgate.sdk.designs import (
    deprecate,
    diff,
    info,
    license_check,
    list_remote,
    pull,
    push,
    quota,
    search,
    stats,
    undeprecate,
    verify,
    watch,
    yank,
)
from fabricgate.sdk.webhooks import (
    webhook_create,
    webhook_delete,
    webhook_deliveries,
    webhook_list,
    webhook_test,
)

__all__ = [
    "ExitKind",
    "FailureKind",
    "SDKError",
    "auth",
    "deprecate",
    "diff",
    "info",
    "license_check",
    "list_remote",
    "login",
    "pull",
    "push",
    "quota",
    "search",
    "stats",
    "token_create",
    "token_list",
    "token_revoke",
    "undeprecate",
    "verify",
    "watch",
    "webhook_create",
    "webhook_delete",
    "webhook_deliveries",
    "webhook_list",
    "webhook_test",
    "yank",
]
