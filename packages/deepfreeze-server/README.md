# deepfreeze-server

Persistent daemon for deepfreeze — REST API, background job management, SSE push events, and the React/Elastic EUI frontend.

Replaces `deepfreeze-web` and `deepfreeze-service` with a single server process that owns all state, scheduling, and job execution. CLI, TUI, and Web UI connect to it as thin clients.

## Installation

```bash
pip install -e packages/deepfreeze-server
```

## Quick Start (Development)

```bash
# Terminal 1 — Server
deepfreeze-server --config ~/.deepfreeze/config.yml --reload

# Terminal 2 — Frontend dev server (hot reload)
cd packages/deepfreeze-server/frontend
npm install
npm run dev
```

Browse to `http://localhost:5173` (Vite dev server proxies API calls to the backend).

## Production Build

Build the frontend so the server serves everything from a single process:

```bash
cd packages/deepfreeze-server/frontend
npm install
npm run build      # outputs to frontend/dist/
```

Then run the server — it auto-detects `frontend/dist/` and serves the built SPA:

```bash
deepfreeze-server --config ~/.deepfreeze/config.yml
```

Browse to `http://<host>:8000`

## Configuration

The server reads the same `~/.deepfreeze/config.yml` used by the CLI. An optional `server` section controls server-specific settings:

```yaml
elasticsearch:
  hosts:
    - https://localhost:9200
  username: elastic
  password: changeme

# Optional — server-specific settings
server:
  host: 0.0.0.0
  port: 8000
  cors_origins:
    - "*"
  refresh_interval: 30.0   # status cache refresh in seconds
```

Environment variable overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPFREEZE_HOST` | `0.0.0.0` | Bind address |
| `DEEPFREEZE_PORT` | `8000` | Listen port |

## CLI Options

```
deepfreeze-server [OPTIONS]

  --config, -c PATH     Path to config file (default: ~/.deepfreeze/config.yml)
  --host HOST           Bind address (overrides config/env)
  --port, -p PORT       Listen port (overrides config/env)
  --reload              Enable auto-reload for development
  --cors-origin URL     Allowed CORS origin (repeatable, default: *)
```

## API Reference

### Health & Readiness

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Basic liveness check (always `{"status": "ok"}`) |
| `GET /ready` | Readiness check — ES connectivity and cache state |

### Status (cached, read-only)

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | Full system status (cluster, repos, thaw, buckets, ILM) |
| `GET /api/status?force_refresh=true` | Bypass cache, fetch fresh from ES |
| `GET /api/status/cluster` | Cluster health only |
| `GET /api/status/repositories` | All repositories |
| `GET /api/status/thaw-requests` | All thaw requests |
| `GET /api/status/buckets` | S3 buckets |
| `GET /api/status/ilm-policies` | ILM policies |
| `GET /api/history` | Recent action history from audit log |
| `GET /api/audit` | Full audit log entries (`?limit=50&action=rotate`) |
| `GET /api/thaw-requests/{id}/restore-progress` | S3 restore progress per repo |

### Actions (mutating)

All action endpoints accept a JSON body and return the action result.

| Endpoint | Body Fields |
|----------|-------------|
| `POST /api/actions/rotate` | `year`, `month`, `keep`, `dry_run` |
| `POST /api/actions/thaw` | `start_date`, `end_date`, `duration`, `tier`, `sync`, `dry_run` |
| `POST /api/actions/thaw/check` | `request_id` (optional — omit to check all) |
| `POST /api/actions/refreeze` | `request_id` (optional — omit for all), `dry_run` |
| `POST /api/actions/cleanup` | `refrozen_retention_days`, `dry_run` |
| `POST /api/actions/repair` | `dry_run` |
| `POST /api/actions/setup` | `repo_name_prefix`, `bucket_name_prefix`, `ilm_policy_name`, `index_template_name`, `dry_run` |

### Jobs

| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs` | List all tracked jobs (`?status=running` to filter) |
| `GET /api/jobs/{id}` | Get a specific job with progress/result/error |
| `DELETE /api/jobs/{id}` | Cancel a running or pending job |

### Server-Sent Events (SSE)

```
GET /api/events               → all events
GET /api/events?channel=jobs  → job lifecycle events only
```

Channels: `jobs`, `status`, `thaw`, `scheduler`

Event types:
- `job.started`, `job.progress`, `job.completed`, `job.failed`, `job.cancelled`
- `status.changed`
- `thaw.completed`
- `scheduler.fired`

Example:

```
event: job.completed
data: {"job_id": "a1b2c3d4e5f6", "type": "rotate", "success": true, "summary": "Action completed successfully"}

event: status.changed
data: {"reason": "rotate_completed"}
```

## Running as a systemd Service

1. Build the frontend (see above).

2. Copy the service file and edit it:

```bash
sudo cp packages/deepfreeze-server/deepfreeze-server.service /etc/systemd/system/
sudo vi /etc/systemd/system/deepfreeze-server.service
```

Update: `User`, `Environment PATH`, `ExecStart` path, `WorkingDirectory`.

3. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable deepfreeze-server
sudo systemctl start deepfreeze-server
```

4. Check status and logs:

```bash
sudo systemctl status deepfreeze-server
journalctl -u deepfreeze-server -f
```

## Architecture

```
deepfreeze-server/
├── deepfreeze_server/
│   ├── app.py                  # FastAPI app factory
│   ├── config.py               # YAML + env var config
│   ├── __main__.py             # uvicorn entry point
│   ├── api/                    # Transport layer (REST + SSE)
│   │   ├── status.py           # GET /api/status/*
│   │   ├── actions.py          # POST /api/actions/*
│   │   ├── jobs.py             # GET/DELETE /api/jobs/*
│   │   ├── events.py           # GET /api/events (SSE)
│   │   ├── health.py           # GET /health, /ready
│   │   ├── auth.py             # Auth middleware (Phase 5)
│   │   └── deps.py             # Shared FastAPI dependencies
│   ├── orchestration/          # Service layer
│   │   ├── orchestrator.py     # Central coordinator
│   │   ├── status_cache.py     # Pre-cached ES status
│   │   ├── job_manager.py      # Background job tracking
│   │   └── event_bus.py        # In-process pub/sub
│   └── models/                 # Pydantic models
│       ├── status.py, commands.py, jobs.py, events.py, errors.py
└── frontend/                   # React/EUI SPA
```

Key design decisions:
- **StatusCache** calls `Status._gather_status_info()` directly, bypassing the stdout/JSON capture used by the old service layer
- **EventBus** uses bounded async queues per subscriber with drop-oldest for slow consumers
- **JobManager** tracks jobs in-memory; completed jobs are recorded in the ES audit index
- All blocking ES/S3 calls run in thread pool executors to avoid blocking the event loop

## Migration from deepfreeze-web

The server is a drop-in replacement for `deepfreeze-web`. The API contract is identical — the same REST endpoints with the same request/response shapes. The React frontend works unchanged.

New capabilities:
- `/health` and `/ready` endpoints for operational monitoring
- `/api/jobs` for tracking background job state
- `/api/events` SSE endpoint for push updates
- Background status cache refresh (no more per-request ES queries)
- Automatic cache invalidation after mutating actions

## Web UI Pages

| Page | Description |
|------|-------------|
| Overview | Cluster health, repo/thaw/bucket/ILM counts — click any card for details |
| Repositories | Sortable, searchable repo table with flyout detail view |
| Thaw Requests | Thaw request table with status, date range, repo list |
| Actions | Run Thaw, Cleanup, Refreeze, Fix/Repair, Rotate with dry-run option |
| Activity | Audit log from Elasticsearch with full detail flyouts |
