"""FastAPI application entry point.

Defines the FastAPI app instance and a single ``GET /health`` endpoint used to
report liveness, the resolved application version, and the process uptime.

The version is resolved from the installed distribution metadata when available
(e.g. after ``pip install -e .``) and falls back to a module-level constant so
that running the app directly from a bare checkout via
``uvicorn app.main:app --reload`` continues to report a valid version.
"""

import os
import time
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Response

# Distribution name declared in pyproject.toml; kept in sync with that file.
_DISTRIBUTION_NAME: str = "app"

# Fallback used when the package is not installed (bare-checkout runs). Must
# match the version declared in pyproject.toml.
_FALLBACK_VERSION: str = "0.1.0"

# Captured once at import time; immutable for the lifetime of the process.
START_TIME: float = time.time()

# Read once at import time; number of seconds after process start during which
# the service reports "starting" instead of "ready". A malformed (non-numeric)
# value fails fast at import via ``float()`` — intended behavior for this
# minimalist scaffold.
READY_DELAY_SECONDS: float = float(os.getenv("READY_DELAY_SECONDS", "0"))


def _resolve_version() -> str:
    """Return the installed distribution version, or the hardcoded fallback."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


APP_VERSION: str = _resolve_version()

app = FastAPI(title="app")


@app.get("/health")
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


@app.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """Return service readiness for accepting traffic.

    Unlike ``/health`` (liveness — is the process alive?), this endpoint reports
    readiness — is the process ready to serve requests? During the startup grace
    period (the first ``READY_DELAY_SECONDS`` after process start) it returns
    ``503`` with ``{"status": "starting"}`` so orchestrators withhold traffic;
    afterwards it returns ``200`` with ``{"status": "ready"}``.

    The elapsed time uses the raw ``time.time() - START_TIME`` delta (no
    rounding) to avoid off-by-a-fraction flakiness at the grace boundary.
    """
    elapsed = time.time() - START_TIME
    if elapsed < READY_DELAY_SECONDS:
        response.status_code = 503
        return {"status": "starting"}
    return {"status": "ready"}
