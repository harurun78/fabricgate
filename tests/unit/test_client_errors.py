"""Failure-kind classification lives in client core (real G5)."""

from __future__ import annotations

import pytest

from fabricgate.client.errors import FailureKind
from fabricgate.client.registry_client import NetworkError, RegistryError
from fabricgate.models.api.errors import ErrorDetail, ErrorResponse


def _err(status: int, code: str = "X", message: str = "m") -> RegistryError:
    return RegistryError(status, ErrorResponse(error=ErrorDetail(code=code, message=message)))


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "X", FailureKind.PERMISSION),
        (403, "X", FailureKind.PERMISSION),
        (404, "X", FailureKind.NOT_FOUND),
        (409, "DEPENDENCY_UNRESOLVABLE", FailureKind.UNRESOLVABLE),
        (409, "SHELL_NOT_FOUND", FailureKind.SHELL_NOT_FOUND),
        (409, "VERSION_CONFLICT", FailureKind.INVALID),
        (400, "X", FailureKind.INVALID),
        (422, "X", FailureKind.INVALID),
        (429, "X", FailureKind.INVALID),
        (500, "X", FailureKind.INFRA),
        (503, "X", FailureKind.INFRA),
        (418, "X", FailureKind.GENERIC),
    ],
)
def test_registry_error_kind_classification(status: int, code: str, expected: FailureKind) -> None:
    assert _err(status, code).kind is expected


def test_network_error_kind_is_infra_not_generic() -> None:
    # status_code == 0 must NOT fall through the base classifier to GENERIC.
    assert NetworkError("boom").kind is FailureKind.INFRA


def test_failure_kind_members() -> None:
    assert {k.value for k in FailureKind} == {
        "GENERIC",
        "NOT_FOUND",
        "PERMISSION",
        "INVALID",
        "INFRA",
        "UNRESOLVABLE",
        "SHELL_NOT_FOUND",
    }
