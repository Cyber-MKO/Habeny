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
- **LXC** and its Python bindings: `sudo apt install lxc lxc-utils python3-lxc`
  (the `lxc` Python module is not available via pip — it must come from apt)
- **Python 3.10+** with pip
- **Node.js 18+** (to build or develop the frontend)

## Quick Start

```bash
# Install LXC and the Python bindings
sudo apt install lxc lxc-utils python3-lxc

# Install Python dependencies as root, since the server runs with sudo
sudo pip3 install -r requirements.txt

# Initialize the database and start the API server
sudo python3 main.py
```

The API starts on `http://0.0.0.0:9000`. To use the web UI, build the
frontend first (see below) — the server then serves it at
`http://localhost:9000`.

## Frontend

The React frontend lives in `frontend/` and builds into `static/`
(not committed to git), which the API server picks up automatically:

```bash
cd frontend
npm install
npm run build      # outputs to ../static/, served by the API on :9000
```

For development with hot reload:

```bash
cd frontend
npm run dev        # runs on http://localhost:3000, proxies API to :9000
```

## Project Structure

```
.
├── main.py                  # FastAPI app, all API routes
├── models.py                # Pydantic request/response models
├── utils.py                 # SIEM installers, container helpers, simulation engine
├── db.py                    # SQLite database layer
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
├── app/                     # Modular package scaffold (migration target)
│   ├── core/                # Shell, container, resource helpers
│   ├── installers/          # Per-SIEM installer modules
│   ├── routes/              # FastAPI router modules
│   ├── services/            # Business logic layer
│   └── simulation/          # Attack simulation engine
│
├── tests/                   # Test suite
│   ├── test_db.py           # Database layer tests
│   ├── test_models.py       # Model validation tests
│   └── test_core_shell.py   # Shell command tests
│
└── PLAN.md                  # Modularization roadmap
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
