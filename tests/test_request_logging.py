"""QA tests for the request-logging middleware (this PR's acceptance criteria).

Each test maps to an acceptance criterion (AC1..AC4) from the enriched PR spec:

    AC1 -- Every request is logged with method, path, status code, and
           duration in ms.
    AC2 -- Log format is exactly ``[method] [path] → [status] ([duration]ms)``.
    AC3 -- The ``/health`` endpoint is excluded from the logs.
    AC4 -- The middleware is registered in ``main.py`` before route handlers.

Logging behaviour is exercised against the real app via FastAPI's ``TestClient``
while capturing the ``app.main`` access logger with pytest's ``caplog`` fixture.
An additional isolated app is built for the error-path edge case so the shared
app's routes are left untouched.
"""

import logging
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import HEALTH_PATH, RequestLoggingMiddleware, app

LOGGER_NAME = "app.main"
REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "app" / "main.py"

# Full log line: "GET /some/path → 404 (1.23ms)". Duration is round(x, 2) so it
# may render with 0, 1, or 2 decimals (e.g. "1.0ms", "1.23ms"); allow all.
_LOG_LINE_RE = re.compile(
    r"^(?P<method>[A-Z]+) (?P<path>\S+) → (?P<status>\d{3}|-) "
    r"\((?P<duration>\d+(?:\.\d+)?)ms\)$"
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _access_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return only the access-log records emitted by the middleware logger."""
    return [r for r in caplog.records if r.name == LOGGER_NAME]


def _make_error_client() -> TestClient:
    """Build an isolated app with the middleware and a route that raises.

    Used to exercise the ``try/finally`` error path without mutating the shared
    application under test. ``raise_server_exceptions=False`` lets the 500
    response propagate back through the middleware instead of re-raising.
    """
    err_app = FastAPI(title="err-app")
    err_app.add_middleware(RequestLoggingMiddleware)

    @err_app.get("/boom")
    async def boom() -> dict:  # pragma: no cover - body never returns
        raise RuntimeError("boom")

    return TestClient(err_app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# AC1 -- every request logged with method, path, status code, and duration
# --------------------------------------------------------------------------- #
def test_ac1_request_emits_exactly_one_access_log_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    records = _access_records(caplog)
    assert len(records) == 1, (
        f"expected exactly one access-log line per request, got {len(records)}: "
        f"{[r.getMessage() for r in records]}"
    )


def test_ac1_log_contains_method_path_status_and_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    msg = _access_records(caplog)[0].getMessage()
    m = _LOG_LINE_RE.match(msg)
    assert m, f"log line does not carry all four fields: {msg!r}"
    assert m.group("method") == "GET", f"method wrong in {msg!r}"
    assert m.group("path") == "/does-not-exist", f"path wrong in {msg!r}"
    assert m.group("status") == "404", f"status wrong in {msg!r}"
    assert float(m.group("duration")) >= 0.0, f"duration must be >= 0 in {msg!r}"


def test_ac1_status_code_reflects_actual_response(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    # Negative/edge: a 405 (wrong method on /health-adjacent route) must be
    # logged with the true status, not a hardcoded 200.
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.post("/does-not-exist")  # 405 or 404 depending on routing
    msg = _access_records(caplog)[0].getMessage()
    m = _LOG_LINE_RE.match(msg)
    assert m and m.group("method") == "POST", f"method must be POST: {msg!r}"
    assert m.group("status") in {"404", "405"}, f"unexpected status: {msg!r}"


def test_ac1_logged_at_info_level(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    rec = _access_records(caplog)[0]
    assert rec.levelno == logging.INFO, (
        f"access log should be emitted at INFO, got {rec.levelname}"
    )


def test_ac1_duration_recorded_even_when_handler_raises(
    caplog: pytest.LogCaptureFixture
):
    # Edge case (enrichment): a downstream exception must still produce a log
    # line with a duration thanks to the try/finally.
    err_client = _make_error_client()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        err_client.get("/boom")
    records = _access_records(caplog)
    assert len(records) == 1, f"error path must still log once, got {len(records)}"
    m = _LOG_LINE_RE.match(records[0].getMessage())
    assert m, f"error-path log line malformed: {records[0].getMessage()!r}"
    assert m.group("path") == "/boom", "error-path log must record the path"
    assert float(m.group("duration")) >= 0.0, "error-path log must record a duration"


# --------------------------------------------------------------------------- #
# AC2 -- log format: "[method] [path] → [status] ([duration]ms)"
# --------------------------------------------------------------------------- #
def test_ac2_log_line_matches_exact_format(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    msg = _access_records(caplog)[0].getMessage()
    assert _LOG_LINE_RE.match(msg), (
        f"log line must match '[method] [path] → [status] ([duration]ms)', "
        f"got {msg!r}"
    )


def test_ac2_log_line_uses_unicode_arrow(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    msg = _access_records(caplog)[0].getMessage()
    assert " → " in msg, f"format requires ' → ' between path and status: {msg!r}"


def test_ac2_duration_has_ms_suffix_in_parentheses(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    msg = _access_records(caplog)[0].getMessage()
    assert re.search(r"\(\d+(?:\.\d+)?ms\)$", msg), (
        f"duration must be parenthesised and suffixed with 'ms': {msg!r}"
    )


# --------------------------------------------------------------------------- #
# AC3 -- /health endpoint is excluded from logs
# --------------------------------------------------------------------------- #
def test_ac3_health_request_emits_no_access_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.get(HEALTH_PATH)
    assert resp.status_code == 200, "sanity: /health should still return 200"
    assert _access_records(caplog) == [], (
        "/health must be excluded from access logs, but a line was emitted: "
        f"{[r.getMessage() for r in _access_records(caplog)]}"
    )


def test_ac3_health_exclusion_does_not_suppress_other_paths(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    # Edge case: hitting /health must not accidentally silence a subsequent
    # non-health request in the same session.
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get(HEALTH_PATH)
        client.get("/does-not-exist")
    records = _access_records(caplog)
    assert len(records) == 1, (
        f"only the non-health request should be logged, got "
        f"{[r.getMessage() for r in records]}"
    )
    assert "/does-not-exist" in records[0].getMessage()
    assert HEALTH_PATH not in records[0].getMessage()


def test_ac3_health_exclusion_is_exact_match(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    # Negative test: a path that merely starts with /health (but is not the
    # exact route) must NOT be excluded -- confirms exact-match granularity.
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/healthz")
    records = _access_records(caplog)
    assert len(records) == 1, (
        f"/healthz is not /health and must be logged, got "
        f"{[r.getMessage() for r in records]}"
    )
    assert "/healthz" in records[0].getMessage()


# --------------------------------------------------------------------------- #
# AC4 -- middleware registered in main.py before route handlers
# --------------------------------------------------------------------------- #
def test_ac4_middleware_is_registered_on_app():
    registered = [m.cls for m in app.user_middleware]
    assert RequestLoggingMiddleware in registered, (
        f"RequestLoggingMiddleware must be registered on the app, got {registered}"
    )


def test_ac4_middleware_registered_before_route_definition_in_source():
    src = MAIN_PY.read_text(encoding="utf-8")
    add_idx = src.find("add_middleware")
    route_idx = src.find("@app.get")
    assert add_idx != -1, "main.py must call add_middleware(...)"
    assert route_idx != -1, "main.py must define at least one route handler"
    assert add_idx < route_idx, (
        "middleware registration must appear before route handlers in main.py "
        f"(add_middleware at {add_idx}, first @app.get at {route_idx})"
    )


def test_ac4_middleware_actually_wraps_requests(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    # Behavioural proof that registration is effective, not just declared.
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.get("/does-not-exist")
    assert _access_records(caplog), (
        "registered middleware must actually run and emit a log line"
    )
