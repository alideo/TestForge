"""QA tests for the ``GET /ready`` readiness endpoint (this PR's ACs).

These tests complement the ``/ready`` cases already present in
``tests/test_health.py`` (``test_ac7_*``/``test_ac8_*``) by adding boundary,
edge-case, negative, and documentation coverage. Each test maps to an
acceptance criterion from the enriched PR spec:

    AC-1 -- GET ``/ready`` returns ``200`` with ``{"status": "ready"}`` when
            ``READY_DELAY_SECONDS`` is 0 or unset (also: negative delay, and
            once the startup grace period has elapsed).
    AC-2 -- GET ``/ready`` returns ``503`` with ``{"status": "starting"}`` when
            called within ``READY_DELAY_SECONDS`` of process start; non-GET
            methods return ``405``.
    AC-3 -- Both the 200 and 503 cases are covered by tests (this module plus
            ``tests/test_health.py``).
    AC-4 -- ``README.md`` documents ``GET /ready`` with its response schema and
            the ``READY_DELAY_SECONDS`` environment variable.

``READY_DELAY_SECONDS`` and ``START_TIME`` are captured once at import time, so
the delay-sensitive tests patch the module globals (which the handler reads at
call time) and use a fresh ``TestClient`` to avoid leaking the forced state
into other tests via the module-scoped ``client`` fixture.
"""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


# --------------------------------------------------------------------------- #
# AC-1 -- GET /ready returns 200 {"status": "ready"} when no active delay
# --------------------------------------------------------------------------- #
def test_ac1_ready_returns_200_when_delay_zero(monkeypatch):
    # Explicit default/unset path: READY_DELAY_SECONDS == 0 -> always ready.
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 200, f"GET /ready with 0 delay should be 200, got {resp.status_code}"
    body = resp.json()
    assert body == {"status": "ready"}, f'/ready body should be {{"status": "ready"}}, got {body}'


def test_ac1_ready_returns_json_content_type(monkeypatch):
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("application/json"), f"/ready must return JSON, got {ctype!r}"


def test_ac1_ready_returns_200_with_negative_delay(monkeypatch):
    # Edge case: a negative delay is never "within" the grace window -> ready.
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", -5.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 200, f"GET /ready with negative delay should be 200, got {resp.status_code}"
    body = resp.json()
    assert body == {"status": "ready"}, f'/ready body should be {{"status": "ready"}}, got {body}'


def test_ac1_ready_returns_200_after_grace_elapsed(monkeypatch):
    # Boundary: with START_TIME far in the past, elapsed > delay -> ready.
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 1.0)
    monkeypatch.setattr("app.main.START_TIME", time.time() - 100.0)
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 200, f"GET /ready after grace elapsed should be 200, got {resp.status_code}"
    body = resp.json()
    assert body == {"status": "ready"}, f'/ready body should be {{"status": "ready"}}, got {body}'


# --------------------------------------------------------------------------- #
# AC-2 -- GET /ready returns 503 {"status": "starting"} within grace period
# --------------------------------------------------------------------------- #
def test_ac2_ready_returns_503_within_grace_period(monkeypatch):
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 3600.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 503, f"GET /ready within grace period should be 503, got {resp.status_code}"
    body = resp.json()
    assert body == {"status": "starting"}, f'/ready body should be {{"status": "starting"}}, got {body}'


def test_ac2_ready_503_content_type_is_json(monkeypatch):
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 3600.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("application/json"), f"/ready 503 must return JSON, got {ctype!r}"


def test_ac2_ready_503_at_process_start_boundary(monkeypatch):
    # Boundary: at ~zero elapsed with a positive delay, service is starting.
    monkeypatch.setattr("app.main.READY_DELAY_SECONDS", 10.0)
    monkeypatch.setattr("app.main.START_TIME", time.time())
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 503, f"GET /ready at process start should be 503, got {resp.status_code}"


def test_ac2_post_ready_returns_405():
    # Negative test: /ready is GET-only; POST must be rejected.
    resp = TestClient(app).post("/ready")
    assert resp.status_code == 405, f"POST /ready should be 405, got {resp.status_code}"


def test_ac2_put_ready_returns_405():
    # Negative test: another non-GET method must also be rejected.
    resp = TestClient(app).put("/ready")
    assert resp.status_code == 405, f"PUT /ready should be 405, got {resp.status_code}"


def test_ac2_ready_state_does_not_leak_after_patched_tests():
    # Regression guard: once monkeypatch is undone, /ready is ready again.
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 200, (
        f"/ready should return to 200 after delay-forcing tests, got {resp.status_code}"
    )


# --------------------------------------------------------------------------- #
# AC-4 -- README documents GET /ready, its response schema, and the env var
# --------------------------------------------------------------------------- #
def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_ac4_readme_documents_ready_endpoint():
    text = _readme_text()
    assert "/ready" in text, "README must document the GET /ready endpoint"


def test_ac4_readme_documents_ready_response_schema():
    text = _readme_text()
    for token in ('"ready"', '"starting"', "200", "503"):
        assert token in text, f"README /ready docs must mention {token!r} in the response schema"


def test_ac4_readme_documents_ready_delay_env_var():
    text = _readme_text()
    assert "READY_DELAY_SECONDS" in text, (
        "README must document the READY_DELAY_SECONDS environment variable"
    )
