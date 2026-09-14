"""Common shared types and utilities."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# HTML safety
# ---------------------------------------------------------------------------

# Matches HTML markup patterns that indicate unsafe content:
#   - HTML opening/closing/comment/doctype tags: <tag …>, </tag>, <!--, <!DOCTYPE
#   - JavaScript event handler attributes: onclick=, onload=, onerror=, …
#   - Dangerous URL schemes: javascript:, vbscript:
#
# Known limitation: `< script>` (space after `<`) is not matched, but browsers
# do not interpret such tokens as tags, so it poses no XSS risk.
_UNSAFE_HTML_RE = re.compile(
    r"<[a-zA-Z!]"  # opening tag or comment/doctype
    r"|</[a-zA-Z]"  # closing tag
    r"|\bon[a-z]{2,}\s*="  # JS event handlers (onclick=, onerror=, …)
    r"|javascript\s*:"  # javascript: URLs
    r"|vbscript\s*:",  # vbscript: URLs
    re.IGNORECASE,
)


def reject_unsafe_html(value: str | None) -> str | None:
    """Raise ``ValueError`` if *value* contains HTML markup or unsafe patterns.

    Plain text and Markdown syntax (``#``, ``*``, backticks, etc.) are
    unaffected.  Rejects:

    * HTML tags — ``<script>``, ``<img>``, ``<b>``, etc.
    * JavaScript event-handler attributes — ``onclick=``, ``onerror=``, etc.
    * Dangerous URL schemes — ``javascript:``, ``vbscript:``
    """
    if value is None:
        return value
    if _UNSAFE_HTML_RE.search(value):
        raise ValueError("HTML tags and unsafe content are not permitted in this field")
    return value


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class FabricGateModel(BaseModel):
    """Base class for all FabricGate Pydantic models.

    - strict=True: disallow implicit type coercions
    - extra="forbid": reject unknown fields (YAML-parse models override to "ignore")
    """

    model_config = ConfigDict(
        strict=True,
        frozen=False,
        extra="forbid",
    )


class ApiResponseModel(FabricGateModel):
    """Base class for models that parse API responses on the client side.

    - extra="ignore": tolerate unknown fields so that additive (backward
      compatible) registry changes never break already-released CLI/SDK
      clients (tolerant reader, ADR-014)
    - strict=True is inherited: type coercion stays disallowed

    Server-side request models and local file validation models must NOT
    use this base — they keep extra="forbid" (strict external input
    validation).
    """

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Custom annotated types
# ---------------------------------------------------------------------------

SHA256Digest = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
"""Content-addressable digest: ``sha256:<64-hex>``."""

SemVer = Annotated[
    str,
    Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
]
"""Semantic version: ``X.Y.Z`` (no pre-release)."""

DesignName = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?/[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
        max_length=128,
    ),
]
"""Design name: ``namespace/design`` (lowercase alphanumeric + hyphen)."""

NamespaceName = Annotated[
    str,
    Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", max_length=64),
]
"""Namespace: lowercase alphanumeric + hyphen."""

PlatformId = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?/[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
    ),
]
"""Platform identifier: ``device/runtime``."""

DesignRef = Annotated[
    str,
    Field(
        pattern=(
            r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?/[a-z0-9]([a-z0-9-]*[a-z0-9])?"
            r":(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
        ),
    ),
]
"""Design reference: ``namespace/design:version``."""

SpdxExpression = Annotated[
    str,
    Field(
        pattern=r"^([A-Za-z0-9\-.+]+)(\s+(AND|OR|WITH)\s+[A-Za-z0-9\-.+]+)*$",
        max_length=512,
    ),
]
"""SPDX license expression (e.g. ``MIT``, ``MIT AND Apache-2.0``)."""

# SPDX License List 3.25 — common identifiers.
# Full list: https://spdx.org/licenses/
# ``LicenseRef-*`` user-defined references are always accepted.
SPDX_LICENSE_IDS: frozenset[str] = frozenset(
    {
        "0BSD",
        "AAL",
        "AFL-3.0",
        "AGPL-1.0-only",
        "AGPL-1.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "Apache-1.0",
        "Apache-1.1",
        "Apache-2.0",
        "APSL-1.0",
        "APSL-1.1",
        "APSL-2.0",
        "Artistic-1.0",
        "Artistic-2.0",
        "BlueOak-1.0.0",
        "BSD-1-Clause",
        "BSD-2-Clause",
        "BSD-2-Clause-Patent",
        "BSD-3-Clause",
        "BSD-3-Clause-LBNL",
        "BSL-1.0",
        "CAL-1.0",
        "CAL-1.0-Combined-Work-Exception",
        "CATOSL-1.1",
        "CC-BY-1.0",
        "CC-BY-2.0",
        "CC-BY-2.5",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-NC-1.0",
        "CC-BY-NC-2.0",
        "CC-BY-NC-2.5",
        "CC-BY-NC-3.0",
        "CC-BY-NC-4.0",
        "CC-BY-NC-ND-1.0",
        "CC-BY-NC-ND-2.0",
        "CC-BY-NC-ND-2.5",
        "CC-BY-NC-ND-3.0",
        "CC-BY-NC-ND-4.0",
        "CC-BY-NC-SA-1.0",
        "CC-BY-NC-SA-2.0",
        "CC-BY-NC-SA-2.5",
        "CC-BY-NC-SA-3.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-ND-1.0",
        "CC-BY-ND-2.0",
        "CC-BY-ND-2.5",
        "CC-BY-ND-3.0",
        "CC-BY-ND-4.0",
        "CC-BY-SA-1.0",
        "CC-BY-SA-2.0",
        "CC-BY-SA-2.5",
        "CC-BY-SA-3.0",
        "CC-BY-SA-4.0",
        "CC0-1.0",
        "CDDL-1.0",
        "CDDL-1.1",
        "CECILL-2.1",
        "CNRI-Python",
        "CPAL-1.0",
        "CUA-OPL-1.0",
        "ECL-1.0",
        "ECL-2.0",
        "EFL-1.0",
        "EFL-2.0",
        "Entessa",
        "EPL-1.0",
        "EPL-2.0",
        "EUDatagrid",
        "EUPL-1.1",
        "EUPL-1.2",
        "Fair",
        "Frameworx-1.0",
        "FSFAP",
        "FTL",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "HPND",
        "Intel",
        "IPA",
        "IPL-1.0",
        "ISC",
        "JSON",
        "LAL-1.2",
        "LAL-1.3",
        "LGPL-2.0-only",
        "LGPL-2.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "LiLiQ-P-1.1",
        "LiLiQ-R-1.1",
        "LiLiQ-Rplus-1.1",
        "LPL-1.0",
        "LPL-1.02",
        "LPPL-1.0",
        "LPPL-1.1",
        "LPPL-1.2",
        "LPPL-1.3a",
        "LPPL-1.3c",
        "MIT",
        "MIT-0",
        "Motosoto",
        "MPL-1.0",
        "MPL-1.1",
        "MPL-2.0",
        "MPL-2.0-no-copyleft-exception",
        "MS-PL",
        "MS-RL",
        "MulanPSL-2.0",
        "Multics",
        "NASA-1.3",
        "NCSA",
        "NGPL",
        "Nokia",
        "NPOSL-3.0",
        "NTP",
        "OCLC-2.0",
        "OFL-1.0",
        "OFL-1.1",
        "OGTSL",
        "OLDAP-2.8",
        "OSET-PL-2.1",
        "OSL-1.0",
        "OSL-1.1",
        "OSL-2.0",
        "OSL-2.1",
        "OSL-3.0",
        "PHP-3.0",
        "PHP-3.01",
        "PostgreSQL",
        "PSF-2.0",
        "QPL-1.0",
        "RPL-1.1",
        "RPL-1.5",
        "RPSL-1.0",
        "RSCPL",
        "SimPL-2.0",
        "SISSL",
        "Sleepycat",
        "SPL-1.0",
        "UCL-1.0",
        "Unicode-DFS-2016",
        "Unlicense",
        "UPL-1.0",
        "VSL-1.0",
        "W3C",
        "Watcom-1.0",
        "WTFPL",
        "Xnet",
        "Zlib",
        "ZPL-2.0",
        "ZPL-2.1",
    }
)


# Common SPDX exception identifiers (used after WITH operator).
SPDX_EXCEPTION_IDS: frozenset[str] = frozenset(
    {
        "389-exception",
        "Autoconf-exception-2.0",
        "Autoconf-exception-3.0",
        "Autoconf-exception-generic",
        "Autoconf-exception-macro",
        "Bison-exception-1.24",
        "Bison-exception-2.2",
        "Bootloader-exception",
        "Classpath-exception-2.0",
        "CLISP-exception-2.0",
        "DigiRule-FOSS-exception",
        "eCos-exception-2.0",
        "Fawkes-Runtime-exception",
        "FLTK-exception",
        "Font-exception-2.0",
        "freertos-exception-2.0",
        "GCC-exception-3.1",
        "LGPL-3.0-linking-exception",
        "Libtool-exception",
        "Linux-syscall-note",
        "LLVM-exception",
        "LZMA-exception",
        "Nokia-Qt-exception-1.1",
        "OCaml-LGPL-linking-exception",
        "OpenVPN-openssl-exception",
        "PS-or-PDF-font-exception-20170817",
        "Qt-LGPL-exception-1.1",
        "Swift-exception",
        "u-boot-exception-2.0",
        "Universal-FOSS-exception-1.0",
        "WxWindows-exception-3.1",
    }
)


def extract_spdx_identifiers(expression: str) -> list[str]:
    """Extract individual license identifiers from an SPDX expression.

    Splits on ``AND``, ``OR``, ``WITH`` operators and returns the
    identifiers (excluding operators).
    """
    return re.split(r"\s+(?:AND|OR|WITH)\s+", expression)


def find_unknown_spdx_ids(expression: str) -> list[str]:
    """Return identifiers in *expression* not in the known SPDX list.

    ``LicenseRef-*`` user-defined references are always accepted.
    Identifiers after ``WITH`` are checked against SPDX exception list.
    """
    unknown: list[str] = []
    # Split on AND / OR first, then handle WITH within each part
    parts = re.split(r"\s+(?:AND|OR)\s+", expression)
    for part in parts:
        with_split = re.split(r"\s+WITH\s+", part, maxsplit=1)
        license_id = with_split[0]
        # Check the license identifier
        if not license_id.startswith("LicenseRef-") and license_id not in SPDX_LICENSE_IDS:
            unknown.append(license_id)
        # Check the exception identifier (if present)
        if len(with_split) > 1:
            exc_id = with_split[1]
            if not exc_id.startswith("LicenseRef-") and exc_id not in SPDX_EXCEPTION_IDS:
                unknown.append(exc_id)
    return unknown


class SpeedGrade(FabricGateModel):
    """Speed grade compatibility info."""

    min: str
    tested: list[str] = Field(default_factory=list)


class Pagination(FabricGateModel):
    """Pagination metadata for list responses."""

    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)
