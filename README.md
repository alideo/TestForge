# Project Overview

A minimal Python FastAPI application that provides a starting point for the
project. It ships a single `GET /health` endpoint that reports service status,
the application version, and process uptime, giving new developers a working
base to build features on.

## Prerequisites

- **Python 3.11+** — a recent interpreter is expected.
- **A virtual environment** — use `python -m venv` (or an equivalent tool) to
  keep dependencies isolated from your system Python.
- **pip** — the standard Python package installer, bundled with modern Python.

## Installation

1. Clone the repository (replace the placeholder with the real URL):

   ```bash
   git clone https://github.com/your-org/your-repo.git
   cd your-repo
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install the runtime dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

Start the development server with uvicorn:

```bash
uvicorn app.main:app --reload
```

Then query the health endpoint:

```bash
curl http://localhost:8000/health
```

The endpoint responds with JSON containing `status`, `version`, and
`uptime_seconds`.

The service also exposes a readiness endpoint used by orchestrators to decide
when to send traffic:

```bash
curl http://localhost:8000/ready
```

`GET /ready` reports whether the process is ready to accept traffic:

- `200 OK` with `{"status": "ready"}` once the service is ready.
- `503 Service Unavailable` with `{"status": "starting"}` during the startup
  grace period.

The grace period is controlled by the `READY_DELAY_SECONDS` environment
variable (default `0`): the number of seconds after process start during which
`/ready` reports `starting`. The value must be numeric — a malformed value
fails fast at startup.

In Kubernetes, wire the readiness probe to `/ready` and the liveness probe to
`/health` so rolling restarts and graceful shutdowns behave correctly.

## Configuration

Any environment-specific settings should be provided via placeholders — never
commit real values:

- `API_KEY` — set to your own key, e.g. `<API_KEY>`.
- `API_HOST` — the service host, e.g. `example.com`.

## License

Released under the MIT License. See the [`LICENSE`](LICENSE) file for details.
Copyright (c) 2026 Ali Asghar.
