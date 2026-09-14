"""Design management SDK functions, split by responsibility.

Implementations live in responsibility-scoped submodules (search, push, pull,
lifecycle, diff, quota, stats, license, watch).  The public functions are
re-exported here so ``fabricgate.sdk.api`` and existing imports
(``from fabricgate.sdk.designs import ...``) keep working unchanged.
"""

from __future__ import annotations

from fabricgate.sdk.designs.diff import diff
from fabricgate.sdk.designs.license import license_check
from fabricgate.sdk.designs.lifecycle import deprecate, undeprecate, yank
from fabricgate.sdk.designs.pull import pull, verify
from fabricgate.sdk.designs.push import push
from fabricgate.sdk.designs.quota import quota
from fabricgate.sdk.designs.search import info, search
from fabricgate.sdk.designs.stats import stats
from fabricgate.sdk.designs.watch import watch

__all__ = [
    "deprecate",
    "diff",
    "info",
    "license_check",
    "pull",
    "push",
    "quota",
    "search",
    "stats",
    "undeprecate",
    "verify",
    "watch",
    "yank",
]
