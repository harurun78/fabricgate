"""License / tool-requirement check SDK function."""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient
from fabricgate.models.cli import LicenseCheckInfo, LicenseCheckToolReq, LicenseCheckVerdict
from fabricgate.sdk._helpers import _parse_design_ref, _registry_errors


def license_check(
    design_ref: str,
    *,
    tool: list[str] | None = None,
    edition: str | None = None,
    registry: str = "https://registry.fabricgate.dev/api/v1",
) -> LicenseCheckInfo:
    """Check tool requirements for a design version.

    Parameters
    ----------
    design_ref:
        ``namespace/design:version``
    tool:
        Tool identifiers to check (e.g. ``["vivado"]``).
    edition:
        Edition to check (e.g. ``"standard"``).
    registry:
        Base URL for the registry API.

    Returns
    -------
    LicenseCheckInfo
        Tool requirements and optional check result.
    """
    namespace, design, version = _parse_design_ref(design_ref)

    with _registry_errors(), RegistryClient(base_url=registry) as client:
        resp = client.license_check(namespace, design, version, tool, edition)

    tool_reqs = [
        LicenseCheckToolReq(
            tool=r.tool,
            min_version=r.min_version,
            edition=r.edition,
            required=r.required,
            note=r.note,
        )
        for r in resp.tool_requirements
    ]

    check = None
    if resp.check is not None:
        check = LicenseCheckVerdict(
            tool=resp.check.tool,
            edition=resp.check.edition,
            meets_requirements=resp.check.meets_requirements,
            notes=list(resp.check.notes),
        )

    return LicenseCheckInfo(
        design=resp.design,
        version=resp.version,
        tool_requirements=tool_reqs,
        check=check,
        disclaimer=resp.disclaimer,
    )
