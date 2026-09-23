# Habeny — Multi-SIEM Container Emulation Platform

LXC-based platform for deploying containers that run SIEM agents at scale.
Deploy hundreds of lightweight containers, each running a real SIEM agent,
to stress-test and validate your SIEM infrastructure.

## Supported SIEM Types

| Type | Agent | Registration |
|------|-------|-------------|
| **Wazuh** | wazuh-agent | Auto-registers with manager |
| **OSSEC** | ossec-hids-agent | Atomicorp installer + agent-auth |
| **OSSIM** | AlienVault agent | Config-based |
| **UTMstack** | utmstack_agent_service | Auth key enrollment |
| **Elastic** | elastic-agent | Fleet enrollment token |
| **None** | — | Bare container (no agent) |

## Prerequisites

- **Ubuntu 22.04+** host
- **Root access** (LXC requires root)
- **LXC** installed: `sudo apt install lxc lxc-utils`
- **Python 3.10+** with pip
- **Node.js 18+** (to build and run the frontend)

## Quick Start

```bash
# Install Python dependencies
pip install -r requirements.txt

# Build the frontend (if needed) and start the API server
sudo ./start.sh
```

Open `http://<host>:9000` — the API and the web UI are both served from there.
`start.sh` installs the frontend's npm dependencies on first run and rebuilds
`static/` whenever the sources in `frontend/` have changed.

## Authentication

The web UI and the API require signing in. On first start there are no accounts:
open the UI and it asks you to **create the admin account**. After that, the
sign-in page is shown to anyone without a valid session.

- Sessions are HttpOnly cookies, valid for 7 days (`HABENY_SESSION_TTL_HOURS` to change).
- After 10 failed sign-ins from one IP within 15 minutes, further attempts are refused for a while.
- Sign-ins, failed sign-ins and the initial setup are recorded in the Activity log.
- Until the admin account exists, anyone who can reach the server can create it,
  so complete setup right after the first start.

**Forgotten password:** remove the account(s) on the server and the UI will offer setup again:

```bash
sudo python3 -c "import sqlite3; c = sqlite3.connect('/var/lib/lxc-siem-platform/platform.db'); c.execute('DELETE FROM sessions'); c.execute('DELETE FROM users'); c.commit()"
```

## Frontend

For development with hot reload, run the API and the Vite dev server together:

```bash
sudo ./start.sh --dev   # UI on http://<host>:3000, proxies API to :9000
```

To build the frontend manually:

```bash
cd frontend
npm install
npm run build      # outputs to ../static/
```

## Project Structure

```
.
├── main.py                  # Entry point: logging setup + create_app()
├── start.sh                 # Quick start: builds frontend, runs API
├── app/                     # FastAPI application
│   ├── __init__.py          # create_app(): storage init, middleware, routers
│   ├── config.py            # Paths and tunables
│   ├── state.py             # In-memory state shared by routes/services
│   ├── middleware.py        # /api prefix stripping, latency tracking
│   ├── db.py                # SQLite database layer
│   ├── routes/              # One APIRouter per domain (agents, groups, ...)
│   ├── services/            # Deployment, simulations, reporting, logs, benchmarks, ...
│   ├── core/                # Shell/lxc-attach, container, network, resources, helpers
│   ├── installers/          # One module per SIEM agent + batch dispatcher, package cache
│   ├── simulation/          # Attack simulation engine
│   └── models/              # Pydantic models by domain (import from app.models)
├── requirements.txt         # Python dependencies
├── ruff.toml                # Python linter config (ruff)
├── index.legacy.html        # Legacy single-file frontend
│
├── frontend/                # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx          # Router, layout, sidebar
│   │   ├── api.js           # API client
│   │   ├── ws.js            # WebSocket hook for live metrics
│   │   ├── store.jsx        # Global state context
│   │   ├── pages/           # Page components
│   │   └── components/      # Reusable UI components
│   └── .eslintrc.cjs        # JavaScript linter config
│
├── tests/                   # Test suite
│   ├── test_db.py           # Database layer tests
│   ├── test_models.py       # Model validation tests
│   └── test_core_shell.py   # Shell command tests
```

## API Endpoints

### System
- `GET /` — API info
- `GET /system/info` — Platform and LXC details
- `GET /system/health` — Health check

### Containers
- `POST /agents/deploy` — Deploy containers with SIEM agents
- `GET /agents` — List containers (filterable, paginated)
- `GET /agents/{id}` — Container detail
- `POST /agents/{id}/start` — Start a container
- `POST /agents/{id}/stop` — Stop a container
- `DELETE /agents/{id}` — Delete a container
- `POST /agents/bulk/{operation}` — Bulk start/stop/delete

### Manager Profiles
- `GET /managers` — List saved profiles
- `POST /managers` — Create a profile
- `GET /managers/{id}` — Get a profile
- `PUT /managers/{id}` — Update a profile
- `DELETE /managers/{id}` — Delete a profile

### Groups
- `GET /groups` — List groups
- `POST /groups` — Create a group
- `POST /groups/{name}/assign` — Assign containers
- `POST /groups/{name}/remove` — Remove containers
- `DELETE /groups/{name}` — Delete a group

### Simulations
- `POST /simulations/start` — Attack simulation
- `POST /simulations/load` — Custom EPS log simulation
- `POST /simulations/syslog/start` — Syslog simulation
- `GET /simulations` — List simulations
- `POST /simulations/{id}/stop` — Stop a simulation

### Reports & Logs
- `POST /reports/generate` — Generate report (JSON/CSV/PDF)
- `GET /reports/{id}/download` — Download report
- `POST /agents/{id}/logs/upload` — Upload logs to container
- `GET /activity/logs` — Activity audit log

### WebSocket
- `WS /ws/metrics` — Live platform metrics (5s interval)
- `WS /ws/console/{name}` — Interactive container terminal

## Linting

```bash
# Python (ruff)
pip install ruff
ruff check .
ruff format .

# JavaScript (eslint)
cd frontend && npx eslint src/
```

## Testing

```bash
pip install pytest
python3 -m pytest tests/ -v
```

## License

Proprietary — Habeny Platform.
