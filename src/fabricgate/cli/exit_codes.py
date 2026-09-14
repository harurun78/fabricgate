"""CLI exit-code policy (ADR-008).

The SDK is exit-code-free and tags failures with a semantic :class:`FailureKind`.
This module is the single place that maps a kind to a process exit code, so the
same failure yields the same code across every subcommand. New commands MUST
reuse this table rather than hard-coding numbers.
"""

from __future__ import annotations

from fabricgate.client.errors import FailureKind
from fabricgate.sdk.api import SDKError

# Semantic kind → process exit code. See docs/specs/cli-specification.md §2.1.
EXIT_CODE: dict[FailureKind, int] = {
    FailureKind.GENERIC: 1,
    FailureKind.NOT_FOUND: 1,
    FailureKind.PERMISSION: 2,
    FailureKind.INVALID: 3,
    FailureKind.INFRA: 4,
    FailureKind.UNRESOLVABLE: 5,
    FailureKind.SHELL_NOT_FOUND: 6,
}


def exit_code_for(exc: SDKError) -> int:
    """Return the process exit code for an SDKError's semantic kind."""
    return EXIT_CODE.get(exc.code, 1)
