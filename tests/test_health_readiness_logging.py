"""QA tests for the health/readiness/request-logging PR.

Each test maps to an acceptance criterion from the enriched PR spec:

    AC9  -- GET /health returns 200 with a JSON body containing
            ``status == "ok"`` and an ISO8601 ``timestamp``, no auth required.
    AC10 -- GET /health/ready returns 200 when the readiness probe is up and
            503 when it is down (DB-down scenario).
    AC11 -- The request-logger middleware emits one structured JSON line per
            request containing method, path, status_code, duration_ms, and
            timestamp.
    AC12 -- The logger uses the stdlib ``logging`` module (existing library),
            adding no new dependency.

Import-time / probe state is exercised deterministically by monkeypatching the
readiness seam (``app.main._check_readiness``) and, where the module-scoped
``client`` fixture must not observe the mutation, by using a fresh
``TestClient(app)`` per the project's testing conventions.
"""

import json
import logging
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _assert_iso8601(value) -> None:
    """Assert ``value`` is a string parseable as an ISO8601 timestamp."""
    assert isinstance(value, str) and value, f"timestamp must be a non-empty string, got {value!r}"
    # datetime.fromisoformat accepts the offset-aware output of .isoformat().
    parsed = datetime.fromisoformat(value)
    assert parsed is not None, f"timestamp must be ISO8601-parseable, got {value!r}"


# --------------------------------------------------------------------------- #
# AC9 -- GET /health returns 200 with {"status": "ok", "timestamp": <ISO8601>}
#         and requires no authentication
# --------------------------------------------------------------------------- #
def test_ac9_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200, f"GET /health should return 200, got {resp.status_code}"


def test_ac9_health_status_is_ok(client: TestClient):
    body = client.get("/health").json()
    assert body.get("status") == "ok", f"/health status must be 'ok', got {body.get('status')!r}"


def test_ac9_health_timestamp_is_iso8601(client: TestClient):
    body = client.get("/health").json()
    assert "timestamp" in body, f"/health body must include 'timestamp', got {body}"
    _assert_iso8601(body["timestamp"])


def test_ac9_health_requires_no_auth(client: TestClient):
    # Negative test: no Authorization header is sent, yet the request succeeds.
    resp = client.get("/health")
    assert resp.status_code == 200, (
        f"/health must be reachable without auth, got {resp.status_code}"
    )
    assert "www-authenticate" not in {k.lower() for k in resp.headers}, (
        "/health must not challenge for authentication"
    )


def test_ac9_health_returns_json_content_type(client: TestClient):
    ctype = client.get("/health").headers.get("content-type", "")
    assert ctype.startswith("application/json"), f"/health must return JSON, got {ctype!r}"


# --------------------------------------------------------------------------- #
# AC10 -- GET /health/ready returns 200 when ready, 503 when the dependency
#          (DB) is unreachable
# --------------------------------------------------------------------------- #
def test_ac10_ready_returns_200_when_up(client: TestClient):
    # Happy path: default readiness probe reports the service is up.
    resp = client.get("/health/ready")
    assert resp.status_code == 200, f"GET /health/ready should be 200 when up, got {resp.status_code}"
    assert resp.json().get("status") == "ready", f"expected status 'ready', got {resp.json()}"


def test_ac10_ready_returns_503_when_db_down(monkeypatch):
    # DB-down scenario: monkeypatch the readiness seam to report unavailable.
    # A fresh TestClient is used so this mutation does not leak into the
    # module-scoped `client` fixture (project convention).
    monkeypatch.setattr("app.main._check_readiness", lambda: False)
    local_client = TestClient(app)
    resp = local_client.get("/health/ready")
    assert resp.status_code == 503, (
        f"GET /health/ready should be 503 when DB is down, got {resp.status_code}"
    )
    assert resp.json().get("status") == "unavailable", (
        f"503 body should report 'unavailable', got {resp.json()}"
    )


def test_ac10_ready_recovers_to_200_after_down(monkeypatch):
    # Edge case: readiness is dynamic -- it flips back to 200 once the probe
    # recovers, proving the status is not cached at import time.
    monkeypatch.setattr("app.main._check_readiness", lambda: True)
    resp = TestClient(app).get("/health/ready")
    assert resp.status_code == 200, f"ready should recover to 200, got {resp.status_code}"


def test_ac10_ready_down_does_not_leak_detail(monkeypatch):
    # Negative test: the unavailable response must not leak internal detail.
    monkeypatch.setattr("app.main._check_readiness", lambda: False)
    body = TestClient(app).get("/health/ready").json()
    assert set(body) == {"status"}, f"unavailable body should only expose 'status', got {body}"


def test_ac10_ready_only_get_allowed(client: TestClient):
    # Negative test: /health/ready is a GET endpoint; POST must be rejected.
    resp = client.post("/health/ready")
    assert resp.status_code == 405, f"POST /health/ready should be 405, got {resp.status_code}"


# --------------------------------------------------------------------------- #
# AC11 -- Request-logger middleware emits one structured JSON line per request
#          with method, path, status_code, duration_ms, timestamp
# --------------------------------------------------------------------------- #
_LOGGER_NAME = "app.request"
_REQUIRED_LOG_KEYS = {"method", "path", "status_code", "duration_ms", "timestamp"}


def test_ac11_middleware_logs_one_line_per_request(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        client.get("/health")
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(records) == 1, f"expected exactly one log line per request, got {len(records)}"


def test_ac11_log_line_is_structured_json_with_required_fields(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        client.get("/health")
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert records, "middleware must emit a log record for the request"
    payload = json.loads(records[0].getMessage())  # must be valid JSON (structured)
    missing = _REQUIRED_LOG_KEYS - set(payload)
    assert not missing, f"log line missing required fields: {sorted(missing)} (got {payload})"


def test_ac11_log_line_records_correct_method_and_path(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        client.get("/health")
    payload = json.loads([r for r in caplog.records if r.name == _LOGGER_NAME][0].getMessage())
    assert payload["method"] == "GET", f"logged method should be GET, got {payload['method']!r}"
    assert payload["path"] == "/health", f"logged path should be /health, got {payload['path']!r}"


def test_ac11_log_line_records_correct_status_and_numeric_duration(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        client.get("/health")
    payload = json.loads([r for r in caplog.records if r.name == _LOGGER_NAME][0].getMessage())
    assert payload["status_code"] == 200, f"logged status should be 200, got {payload['status_code']}"
    duration = payload["duration_ms"]
    assert isinstance(duration, (int, float)) and not isinstance(duration, bool), (
        f"duration_ms must be numeric, got {type(duration).__name__}"
    )
    assert duration >= 0, f"duration_ms must be non-negative, got {duration}"
    _assert_iso8601(payload["timestamp"])


def test_ac11_middleware_logs_error_responses(client: TestClient, caplog):
    # Edge case: the middleware runs at the outermost layer, so 4xx/5xx are
    # also logged. An unknown route (404) must still produce one log line.
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        client.get("/does-not-exist")
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(records) == 1, f"error responses must also be logged once, got {len(records)}"
    payload = json.loads(records[0].getMessage())
    assert payload["status_code"] == 404, f"logged status should be 404, got {payload['status_code']}"
    assert payload["path"] == "/does-not-exist"


def test_ac11_middleware_logs_readiness_down_request(monkeypatch, caplog):
    # Cross-feature: a 503 readiness response is logged with its real status.
    monkeypatch.setattr("app.main._check_readiness", lambda: False)
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        TestClient(app).get("/health/ready")
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(records) == 1, f"expected one log line for the readiness request, got {len(records)}"
    payload = json.loads(records[0].getMessage())
    assert payload["status_code"] == 503, f"logged status should be 503, got {payload['status_code']}"


# --------------------------------------------------------------------------- #
# AC12 -- Logger uses the existing stdlib logging library; no new dependency
# --------------------------------------------------------------------------- #
def test_ac12_logger_is_stdlib_logging_instance():
    import app.main as main

    assert isinstance(main.logger, logging.Logger), (
        "request logger must be a stdlib logging.Logger instance"
    )
    assert main.logger.name == _LOGGER_NAME, f"unexpected logger name: {main.logger.name!r}"


def test_ac12_no_new_dependencies_added():
    # The PR must not introduce a new logging dependency. Assert the declared
    # dependency set is still exactly fastapi + uvicorn (stdlib logging only).
    import tomllib
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = [d.lower() for d in pyproject["project"]["dependencies"]]
    names = {d.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip() for d in deps}
    assert names == {"fastapi", "uvicorn"}, (
        f"no new runtime dependency should be added for logging, got {sorted(names)}"
    )
