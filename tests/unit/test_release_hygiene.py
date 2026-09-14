"""Release hygiene for the public package.

- release.yaml only fires on stable tags and grants the reusable CI job the
  permissions it declares (a called workflow cannot hold more than the caller).
- The publication boundary: no registry code ships in this repository.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RELEASE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yaml"


def _release_workflow() -> dict:
    wf = yaml.safe_load(_RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))  # PyYAML parses bare `on` as True
    return wf


def _gh_glob_to_regex(pattern: str) -> str:
    out = []
    for ch in pattern:
        if ch == ".":
            out.append(r"\.")
        elif ch == "*":
            out.append(".*")
        else:
            out.append(ch)
    return "^" + "".join(out) + "$"


def _release_tag_matches(tag: str) -> bool:
    patterns = _release_workflow()["on"]["push"]["tags"]
    return any(re.match(_gh_glob_to_regex(p), tag) for p in patterns)


def test_release_triggers_on_stable_tags():
    assert _release_tag_matches("v0.1.0")
    assert _release_tag_matches("v1.12.300")


def test_release_ignores_prerelease_tags():
    for tag in ("v0.1.0-staging.6", "v0.1.0rc1", "v0.1", "0.1.0"):
        assert not _release_tag_matches(tag), tag


def test_release_ci_gate_grants_pull_requests_read():
    ci_job = _release_workflow()["jobs"]["ci"]
    assert ci_job.get("permissions", {}).get("pull-requests") == "read"


def test_no_registry_code_in_public_repo():
    assert not (_REPO_ROOT / "src" / "fabricgate" / "registry").exists()


def test_pyproject_has_no_server_dependencies():
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {re.split(r"[<>=!~\[ ]", d, maxsplit=1)[0].lower() for d in data["project"]["dependencies"]}
    assert names.isdisjoint({"fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg2-binary", "boto3"})


def test_fabricgate_is_a_namespace_package():
    """`fabricgate` must stay a PEP 420 namespace package (no __init__.py).

    The private registry distribution installs `fabricgate.registry` next to
    this package; a regular package here would shadow it.
    """
    assert not (_REPO_ROOT / "src" / "fabricgate" / "__init__.py").exists()
    assert (_REPO_ROOT / "src" / "fabricgate" / "_version.py").exists()


def test_version_module_matches_pyproject():
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    module = (_REPO_ROOT / "src" / "fabricgate" / "_version.py").read_text(encoding="utf-8")
    assert re.search(r'__version__ = "([^"]+)"', module).group(1) == pyproject
