"""FastAPI application entry point.

Defines the FastAPI app instance and a single ``GET /health`` endpoint used to
report liveness, the resolved application version, and the process uptime.

The version is resolved from the installed distribution metadata when available
(e.g. after ``pip install -e .``) and falls back to a module-level constant so
that running the app directly from a bare checkout via
``uvicorn app.main:app --reload`` continues to report a valid version.
"""

import logging
import time
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Distribution name declared in pyproject.toml; kept in sync with that file.
_DISTRIBUTION_NAME: str = "app"

# Fallback used when the package is not installed (bare-checkout runs). Must
# match the version declared in pyproject.toml.
_FALLBACK_VERSION: str = "0.1.0"

# Single source of truth for the health route path: used by both the route
# decorator and the request-logging middleware's exclusion check.
HEALTH_PATH: str = "/health"

# Captured once at import time; immutable for the lifetime of the process.
START_TIME: float = time.time()

# Access-log logger. No handler is configured here on purpose (out of scope:
# no log aggregation/shipping); output defers to the ambient logging config.
logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    """Return the installed distribution version, or the hardcoded fallback."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


APP_VERSION: str = _resolve_version()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each HTTP request's method, path, status, and duration in ms.

    Requests to ``HEALTH_PATH`` are excluded to reduce noise. The exclusion is
    an exact-path match (``==``) rather than a prefix so future ``/health*``
    routes are not silently dropped from the logs.

    Duration is measured with ``time.perf_counter()`` (monotonic, immune to
    wall-clock changes) and rounded to two decimal places to keep the log-line
    shape stable across requests. The timing is emitted from a ``finally``
    block so the duration is recorded even when a downstream handler raises.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == HEALTH_PATH:
            return await call_next(request)

        start = time.perf_counter()
        status: object = "-"
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                f"{request.method} {request.url.path} → {status} ({elapsed_ms}ms)"
            )


app = FastAPI(title="app")
app.add_middleware(RequestLoggingMiddleware)


@app.get(HEALTH_PATH)
async def health() -> dict[str, object]:
    """Return service liveness, version, and uptime.

    ``uptime_seconds`` is rounded to two decimal places to keep the payload
    shape stable and predictable across requests.
    """
    return {
        "status": "ok",
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - START_TIME, 2),
    }
