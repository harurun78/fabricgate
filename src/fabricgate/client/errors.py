"""Failure-kind taxonomy for the client core (language-neutral contract).

A :class:`FailureKind` is the semantic category of a client failure, distilled
from a registry error's HTTP status and wire error code. It is owned by the
core so every consumer -- the Python SDK, future native/C++/JS bindings, and
the CLI -- reads the same classification instead of re-deriving it.

The CLI maps a kind to a process exit code (see ``cli/exit_codes.py`` and
ADR-008). Library users (``import fabricgate as fg``) match on
``SDKError.code`` (a ``FailureKind``). See docs/specs/client-behavior.md.
"""

from __future__ import annotations

from enum import StrEnum


class FailureKind(StrEnum):
    """Semantic category of a client failure."""

    GENERIC = "GENERIC"  # unclassified
    NOT_FOUND = "NOT_FOUND"  # named resource absent
    PERMISSION = "PERMISSION"  # not authenticated / 401 / 403 / scope
    INVALID = "INVALID"  # request/content rejected (digest, rate-limit, limits, validation)
    INFRA = "INFRA"  # network / 5xx / local IO / missing external tool
    UNRESOLVABLE = "UNRESOLVABLE"  # platform / dependency cannot be resolved
    SHELL_NOT_FOUND = "SHELL_NOT_FOUND"  # partial bitstream shell unresolvable
