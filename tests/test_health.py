"""QA tests validating the FastAPI app and packaging against the PR ACs.

Each test maps to an acceptance criterion (AC1..AC6) from the enriched PR spec:

    AC1 -- ``app/main.py`` exists and defines a FastAPI app instance.
    AC2 -- GET ``/health`` returns JSON with at least ``status``, ``version``,
           ``uptime_seconds``.
    AC3 -- ``pyproject.toml`` exists with project name, version, dependencies.
    AC4 -- ``requirements.txt`` exists with fastapi and uvicorn pinned.
    AC5 -- ``README.md`` exists with install + run instructions.
    AC6 -- No hardcoded secrets or environment-specific values in any file.

The tests exercise the running app via FastAPI's ``TestClient`` and read the
packaging/documentation files directly from the repository root so the criteria
are verified exactly as they appear on disk.
"""

import re
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "app" / "main.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"
README = REPO_ROOT / "README.md"

# Dirs that are gitignored / off-limits / not part of the delivered source.
_EXCLUDED_DIRS = {"_backup", "ix-forge", ".git", "__pycache__", ".pytest_cache", ".venv"}


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _source_files():
    """Yield in-scope project files (excludes backups, platform, caches)."""
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        yield path


# --------------------------------------------------------------------------- #
# AC1 -- app/main.py exists and defines a FastAPI app instance
# --------------------------------------------------------------------------- #
def test_ac1_main_module_exists():
    assert MAIN_PY.is_file(), "app/main.py must exist at app/main.py"


def test_ac1_app_is_fastapi_instance():
    assert isinstance(app, FastAPI), "app.main.app must be a FastAPI instance"


# --------------------------------------------------------------------------- #
# AC2 -- GET /health returns JSON with status, version, uptime_seconds
# --------------------------------------------------------------------------- #
def test_ac2_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200, f"GET /health should return 200, got {resp.status_code}"


def test_ac2_health_returns_json_content_type(client: TestClient):
    resp = client.get("/health")
    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("application/json"), f"/health must return JSON, got {ctype!r}"


def test_ac2_health_has_required_keys(client: TestClient):
    body = client.get("/health").json()
    required = {"status", "version", "uptime_seconds"}
    missing = required - set(body)
    assert not missing, f"/health JSON missing required keys: {sorted(missing)} (got {body})"


def test_ac2_health_status_is_non_empty_string(client: TestClient):
    status = client.get("/health").json()["status"]
    assert isinstance(status, str) and status, f"'status' must be a non-empty string, got {status!r}"


def test_ac2_health_version_is_non_empty_string(client: TestClient):
    version = client.get("/health").json()["version"]
    assert isinstance(version, str) and version, f"'version' must be a non-empty string, got {version!r}"


def test_ac2_health_uptime_is_non_negative_number(client: TestClient):
    uptime = client.get("/health").json()["uptime_seconds"]
    assert isinstance(uptime, (int, float)) and not isinstance(uptime, bool), (
        f"'uptime_seconds' must be numeric, got {type(uptime).__name__}"
    )
    assert uptime >= 0, f"'uptime_seconds' must be non-negative, got {uptime}"


def test_ac2_health_uptime_is_monotonic_non_decreasing(client: TestClient):
    # Edge case: uptime must not go backwards between successive requests.
    first = client.get("/health").json()["uptime_seconds"]
    second = client.get("/health").json()["uptime_seconds"]
    assert second >= first, f"uptime_seconds went backwards: {first} -> {second}"


def test_ac2_health_only_get_allowed(client: TestClient):
    # Negative test: /health is a GET endpoint; POST must not be accepted.
    resp = client.post("/health")
    assert resp.status_code == 405, f"POST /health should be 405 Method Not Allowed, got {resp.status_code}"


def test_ac2_unknown_route_returns_404(client: TestClient):
    # Negative test: undefined routes should 404, proving routing is real.
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404, f"Unknown route should 404, got {resp.status_code}"


# --------------------------------------------------------------------------- #
# AC3 -- pyproject.toml exists with project name, version, dependencies
# --------------------------------------------------------------------------- #
def test_ac3_pyproject_exists():
    assert PYPROJECT.is_file(), "pyproject.toml must exist at the repository root"


def test_ac3_pyproject_has_name_and_version(pyproject: dict):
    project = pyproject.get("project", {})
    assert project.get("name"), "pyproject.toml [project] must declare a name"
    assert project.get("version"), "pyproject.toml [project] must declare a version"


def test_ac3_pyproject_lists_dependencies(pyproject: dict):
    deps = pyproject.get("project", {}).get("dependencies", [])
    assert deps, "pyproject.toml [project].dependencies must list dependencies"
    joined = " ".join(deps).lower()
    assert "fastapi" in joined, f"dependencies must include fastapi, got {deps}"
    assert "uvicorn" in joined, f"dependencies must include uvicorn, got {deps}"


def test_ac3_pyproject_version_matches_health_version(pyproject: dict, client: TestClient):
    # Version single-sourcing (enrichment): /health version should match pyproject.
    declared = pyproject["project"]["version"]
    served = client.get("/health").json()["version"]
    assert served == declared, (
        f"/health version {served!r} must match pyproject version {declared!r}"
    )


# --------------------------------------------------------------------------- #
# AC4 -- requirements.txt exists with fastapi and uvicorn pinned
# --------------------------------------------------------------------------- #
def test_ac4_requirements_exists():
    assert REQUIREMENTS.is_file(), "requirements.txt must exist at the repository root"


def test_ac4_requirements_pin_fastapi_and_uvicorn():
    lines = [
        ln.strip()
        for ln in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    pin = re.compile(r"[=<>~!]=|[<>]")  # any version specifier
    fastapi_line = next((ln for ln in lines if re.match(r"(?i)^fastapi\b", ln)), None)
    uvicorn_line = next((ln for ln in lines if re.match(r"(?i)^uvicorn\b", ln)), None)
    assert fastapi_line, f"requirements.txt must list fastapi, got {lines}"
    assert uvicorn_line, f"requirements.txt must list uvicorn, got {lines}"
    assert pin.search(fastapi_line), f"fastapi must be pinned/version-constrained: {fastapi_line!r}"
    assert pin.search(uvicorn_line), f"uvicorn must be pinned/version-constrained: {uvicorn_line!r}"


# --------------------------------------------------------------------------- #
# AC5 -- README.md exists with install + run instructions
# --------------------------------------------------------------------------- #
def test_ac5_readme_exists():
    assert README.is_file(), "README.md must exist at the repository root"


def test_ac5_readme_has_install_instructions():
    text = README.read_text(encoding="utf-8").lower()
    assert "install" in text, "README must describe how to install dependencies"
    assert "pip install" in text, "README should show a 'pip install' command"


def test_ac5_readme_has_run_instructions():
    text = README.read_text(encoding="utf-8").lower()
    assert "uvicorn" in text, "README must describe how to run the app (uvicorn command)"


# --------------------------------------------------------------------------- #
# AC6 -- No hardcoded secrets or environment-specific values in any file
# --------------------------------------------------------------------------- #
SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9/+]{16,}", "hardcoded credential value"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key block"),
    (r"(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}", "bearer token"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b", "hardcoded host:port"),
]

PLACEHOLDER_ALLOWLIST = re.compile(
    r"(?i)your-org|your-repo|your_package|<[A-Za-z0-9_]+>|example\.com|xxxx|placeholder|localhost"
)


def test_ac6_no_hardcoded_secrets_in_any_file():
    findings = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # skip binary / unreadable files
        for ln in text.splitlines():
            if PLACEHOLDER_ALLOWLIST.search(ln):
                continue
            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, ln):
                    findings.append(f"{path.relative_to(REPO_ROOT)}: {label}: {ln.strip()}")
    assert not findings, "Possible hardcoded secrets/env-specific values:\n" + "\n".join(findings)
