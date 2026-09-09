"""FastAPI application entry point.

Defines the FastAPI app instance and a single ``GET /health`` endpoint used to
report liveness, the resolved application version, and the process uptime.

The version is resolved from the installed distribution metadata when available
(e.g. after ``pip install -e .``) and falls back to a module-level constant so
that running the app directly from a bare checkout via
``uvicorn app.main:app --reload`` continues to report a valid version.
"""

import json
import logging
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request, Response

# Distribution name declared in pyproject.toml; kept in sync with that file.
_DISTRIBUTION_NAME: str = "app"

# Fallback used when the package is not installed (bare-checkout runs). Must
# match the version declared in pyproject.toml.
_FALLBACK_VERSION: str = "0.1.0"

# Captured once at import time; immutable for the lifetime of the process.
START_TIME: float = time.time()


def _resolve_version() -> str:
    """Return the installed distribution version, or the hardcoded fallback."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


APP_VERSION: str = _resolve_version()

# Named logger for structured per-request access logs. Handler/level
# configuration is intentionally left to the host so this module stays
# side-effect-free at import (no logging.basicConfig, no global handlers).
logger = logging.getLogger("app.request")

app = FastAPI(title="app")


def _check_readiness() -> bool:
    """Return whether the service is ready to accept traffic.

    This is the seam a real dependency probe (e.g. a database ``SELECT 1``)
    would eventually replace. There is no database in this scaffold, so the
    check is structural and always reports ready. Tests monkeypatch this
    function to simulate an unavailable dependency.
    """
    return True


@app.get("/health")
async def health() -> dict[str, object]:
    """Return service liveness, version, uptime, and current timestamp.

    ``uptime_seconds`` is rounded to two decimal places to keep the payload
    shape stable and predictable across requests. ``timestamp`` is an
    ISO8601, timezone-aware instant of when the response was produced.
    """
    return {
        "status": "ok",
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/ready")
async def ready(response: Response) -> dict[str, object]:
    """Return service readiness.

    Reports ``200`` with ``{"status": "ready"}`` when the service can accept
    traffic, or ``503`` with ``{"status": "unavailable"}`` otherwise. The
    unavailable response intentionally leaks no internal detail.
    """
    if _check_readiness():
        return {"status": "ready"}
    response.status_code = 503
    return {"status": "unavailable"}


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    """Emit one structured JSON log line per request.

    Runs at the outermost layer so all responses -- including 4xx/5xx -- are
    logged. Only method, path, status code, duration, and timestamp are
    recorded; query strings, headers, and bodies are deliberately excluded to
    avoid leaking sensitive data.
    """
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 2)
    logger.info(
        json.dumps(
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    return response
