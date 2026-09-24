# Habeny — Multi-SIEM Container Emulation Platform

LXC-based platform for deploying containers that run SIEM agents at scale.
Deploy hundreds of lightweight containers, each running a real SIEM agent,
to stress-test and validate your SIEM infrastructure.

![Habeny dashboard](docs/images/dashboard.png)

## Supported SIEM Types

| Type | Agent | Registration |
|------|-------|-------------|
| **Wazuh** | wazuh-agent | Auto-registers with manager |
| **OSSEC** | ossec-hids-agent | Atomicorp installer + agent-auth |
| **OSSIM** | AlienVault agent | Config-based |
| **UTMstack** | utmstack_agent_service | Auth key enrollment |
| **Elastic** | elastic-agent | Fleet enrollment token |
| **None** | — | Bare container (no agent) |

## Requirements

- **Ubuntu 22.04+ or Debian 12+** host (x86_64), with root access
- **LXC** and its Python bindings (`lxc lxc-utils python3-lxc`; the package and installer add them)
- **Python 3.10+**
- **Node.js 20.19+ or 22.12+** *only* to build the frontend from a git checkout or to
  develop it. Releases ship the frontend prebuilt, so production servers don't need Node.

## Installation

Habeny runs as two systemd services, so the web app never runs as root:

- **habeny**: the web app, as the unprivileged `habeny` user, sandboxed by systemd
  (read-only system, no capabilities; it can only write its data directory).
- **habeny-helper**: a small root service that performs container operations for it
  over a Unix socket (`/run/habeny/helper.sock`, only `habeny`/root may connect). It
  accepts a fixed list of LXC operations and validates every argument: e.g. it will
  set only the network keys the app uses, never hooks or mounts, and create only the
  offered OS images.

Both start at boot and restart if they crash. Download a release from the
[Releases page](https://github.com/Cyber-MKO/Habeny/releases) and pick one way to install:

**Debian/Ubuntu package (recommended)**

```bash
sudo apt install ./habeny_2.1.0_all.deb
```

**Release tarball** (any systemd distribution with apt)

```bash
tar xzf habeny-2.1.0.tar.gz && cd habeny-2.1.0
sudo ./deploy/install.sh
```

**From a git checkout** (builds the frontend, so it needs Node.js 20.19+/22.12+)

```bash
git clone https://github.com/Cyber-MKO/Habeny.git && cd Habeny
sudo ./deploy/install.sh
```

Then open `https://<host>:9000` (see [HTTPS](#https)); the first visit asks for the setup
token (see [Authentication](#authentication)). What gets installed:

| Path | What |
|---|---|
| `/opt/habeny` | The app, root-owned and read-only to the service, with its Python environment in `.venv` |
| `/etc/habeny/habeny.conf` | [Configuration](#configuration) |
| `/var/lib/lxc-siem-platform` | Data: database, backups, encryption key, TLS certificate, reports |
| `habeny.service`, `habeny-helper.service` | The two services |
| `habeny` command | Administration: `sudo habeny --help` |

The installer copies the app, so a checkout or tarball can live anywhere and is left
untouched. `HABENY_INSTALL_DIR` / `HABENY_DATA_DIR` change the two paths at install time
(the install directory must be outside `/home`). An existing install, including one that
ran as root, is upgraded in place and its data kept.

**Without internet access:** the installer gets Python packages from PyPI. For an offline
host, also download `habeny-wheels-<version>-cpXY-x86_64.tar.gz` for the host's Python
(`python3 --version`: 3.10 → cp310, 3.12 → cp312, …) and extract it into the release
directory (tarball install) or `/opt/habeny` (package install) before installing:
`sudo mkdir -p /opt/habeny && sudo tar xzf habeny-wheels-2.1.0-cp312-x86_64.tar.gz -C /opt/habeny`.

**Why no Docker image:** Habeny creates and manages LXC containers on the host. Running
it inside Docker would need a privileged container with access to the host's LXC and
cgroups, which is root on the host with extra steps; the systemd services above are
more secure (and simpler).

Note: containers are privileged LXC containers, so root inside a container is powerful;
the helper keeps web-app bugs from being root on the host, but the console and agent
installs run as root *inside* containers by design.

## Running and stopping

```bash
systemctl status habeny habeny-helper          # state
journalctl -u habeny -u habeny-helper -f       # logs
sudo systemctl restart habeny                  # after changing the configuration
```

**Stopping is graceful.** On `systemctl stop`/`restart` (or an upgrade), Habeny refuses
new changes, lets containers that are already deploying finish, and cancels the ones still
queued. After `HABENY_SHUTDOWN_TIMEOUT` (default 10 minutes) it stops waiting; containers
still deploying are marked **interrupted**. The same happens at the next start for
anything cut off by a crash or power loss. Delete and redeploy interrupted containers.

With an invalid configuration the service doesn't start (and doesn't restart-loop); the
reason is in `journalctl -u habeny`, and `sudo habeny config check` shows it too.

## Configuration

Settings live in **`/etc/habeny/habeny.conf`** (`KEY=value` lines; the installer creates it
with every setting commented out). Environment variables override the file. After a
change: `sudo systemctl restart habeny`.

```bash
sudo habeny config          # every setting, its value and where it came from (secrets hidden)
sudo habeny config check    # validate without restarting
```

Invalid values (a port that isn't a number, an unknown TLS mode, a certificate file that
doesn't exist, ...) stop Habeny at startup with a message naming each problem, and
unknown `HABENY_*` keys in the file are warned about (typos). Upgrading from a version
that used `/etc/default/habeny` moves its settings into the new file.

<!-- Generated from app/config.py: `python3 -m app.cli config docs` (a test checks it's current) -->
| Setting | Default | Description |
|---|---|---|
| `HABENY_HOST` | `0.0.0.0` | Address to listen on |
| `HABENY_PORT` | `9000` | Port to listen on |
| `HABENY_TLS` | `auto` | `auto`: HTTPS (your certificate, else self-signed); `off`: plain HTTP behind a reverse proxy that terminates TLS |
| `HABENY_TLS_CERT` |  | Your certificate (PEM, full chain) |
| `HABENY_TLS_KEY` |  | Its private key (PEM) |
| `HABENY_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Reverse proxies trusted to send X-Forwarded-Proto/-For (comma-separated IPs, or `*`) |
| `HABENY_LOG_LEVEL` | `INFO` | Log level |
| `HABENY_SHUTDOWN_TIMEOUT` | `600` | Seconds a stop/restart waits for running deployments to finish before interrupting them (the systemd unit allows up to 840) |
| `HABENY_DEPLOY_WORKERS` | CPU count | Containers deployed in parallel (default: CPU count) |
| `HABENY_BENCHMARK_WORKERS` | CPU count | Parallel workers for benchmark runs (default: CPU count) |
| `HABENY_SESSION_TTL_HOURS` | `168` | How long a sign-in lasts (hours) |
| `HABENY_PASSWORD_MIN_LENGTH` | `12` | Minimum password length |
| `HABENY_CORS_ORIGINS` |  | Other browser origins allowed to call the API, comma-separated (exact `https://host:port`); empty: none |
| `HABENY_SECRET_KEY` |  | Key encrypting stored SIEM secrets (default: generated in `DATA_DIR/secret.key`) |
| `HABENY_OIDC_ISSUER` |  | OIDC issuer URL; turns single sign-on on |
| `HABENY_OIDC_CLIENT_ID` |  | Client ID from the app registration |
| `HABENY_OIDC_CLIENT_SECRET` |  | Client secret |
| `HABENY_OIDC_REDIRECT_URI` |  | Redirect URI registered at the provider (set it behind a reverse proxy) |
| `HABENY_OIDC_SCOPES` | `openid profile email` | Scopes to request |
| `HABENY_OIDC_USERNAME_CLAIM` | `preferred_username` | Claim used as the username |
| `HABENY_OIDC_GROUPS_CLAIM` | `groups` | Claim listing the user's groups |
| `HABENY_OIDC_ADMIN_GROUPS` |  | Groups whose members are admins (comma-separated) |
| `HABENY_OIDC_OPERATOR_GROUPS` |  | Groups whose members are operators |
| `HABENY_OIDC_VIEWER_GROUPS` |  | Groups whose members are viewers |
| `HABENY_OIDC_DEFAULT_ROLE` | `viewer` | Role for new SSO users when no group mapping is set |
| `HABENY_OIDC_BUTTON_LABEL` | `Sign in with SSO` | Sign-in button text |
| `HABENY_OIDC_CA_BUNDLE` |  | CA file for a provider with a private certificate |
| `HABENY_OIDC_ALLOW_HTTP` | `false` | Allow a plain-HTTP provider (testing only) |
| `HABENY_DATA_DIR` | `/var/lib/lxc-siem-platform` | Database, keys, reports and logs *(set by the installer)* |
| `HABENY_LXC_BACKEND` |  | `helper` (unprivileged app + root helper) or `direct` (app runs as root); default: direct when root, else helper *(set by the installer)* |
| `HABENY_HELPER_SOCKET` | `/run/habeny/helper.sock` | The helper's Unix socket *(set by the installer)* |
| `HABENY_HELPER_USER` | `habeny` | The only user (besides root) the helper accepts *(set by the installer)* |
## Upgrading

Install the newer release the same way you installed Habeny: `sudo apt install
./habeny_<new>_all.deb`, or run `sudo ./deploy/install.sh` from the new tarball or after
`git pull`. The upgrade:

1. stops Habeny gracefully (running deployments finish first, see above),
2. backs up the database to `/var/lib/lxc-siem-platform/backups/`,
3. applies database migrations (each in a transaction: a failure leaves the database as it
   was, and Habeny isn't started on a half-migrated database),
4. starts the new version.

**Database migrations** are numbered steps in `app/migrations/`; the database records
which one it's at. `sudo habeny db status` shows it, pending migrations and backups.
The last 10 backups are kept; `sudo habeny db backup` makes one any time (safe while running).

**Rolling back** to the version you had before an upgrade:

```bash
sudo systemctl stop habeny
sudo habeny db status                    # find the "before-vN" backup taken by the upgrade
sudo habeny db restore /var/lib/lxc-siem-platform/backups/platform-<date>-v1-before-v2.db
sudo apt install ./habeny_<old>_all.deb  # or install.sh from the old release
```

An older Habeny refuses to start on a database a newer one has migrated (it says so and
points to the backups), so data is never silently misread. Where migrations support it,
`sudo habeny db downgrade --to N` undoes them in place instead of restoring a backup.

**Uninstalling:** `sudo apt remove habeny` stops and removes the services and the app
(`apt purge` also removes `/etc/habeny`). The data in `/var/lib/lxc-siem-platform` is kept;
delete it yourself if you no longer need it.

## Development

```bash
pip install -r requirements-dev.txt
sudo ./start.sh          # serves everything on :9000, building the frontend if needed
sudo ./start.sh --dev    # API on :9000 plus the Vite dev server with hot reload on :3000
```

`start.sh` runs Habeny in the foreground from the checkout (settings from
`/etc/habeny/habeny.conf` or `HABENY_*` variables, e.g. `HABENY_DATA_DIR=/tmp/habeny`). It
needs Node.js only when the frontend must be (re)built or for `--dev`.

**Making a release:** bump `app/version.py` in a PR and merge it. Then, on GitHub, open
**Actions → Release → Run workflow** (on `main`), or push the tag yourself
(`git tag v2.1.1 && git push origin v2.1.1`). The Release workflow tags `main` with the
version (refusing one that's already released), runs the tests, builds the frontend, and
publishes the tarball, the `.deb`, offline wheel bundles for Python 3.10–3.13 and
`SHA256SUMS`. Tick **dry run** to build everything and attach it to the workflow run without
publishing. `deploy/build-release.sh` builds the same artifacts locally. **Changing the database schema:** add the next `app/migrations/vNNNN_*.py`
with `up(conn)` (and `down(conn)` if it can be undone); never edit a released one.

## HTTPS

The server speaks **HTTPS only** on port 9000. On first start it generates a
self-signed certificate (`/var/lib/lxc-siem-platform/tls/`), so browsers show a
warning once; traffic is encrypted either way.

To use your own certificate, set `HABENY_TLS_CERT` and `HABENY_TLS_KEY` (PEM paths) in
`/etc/habeny/habeny.conf`; that also turns on HSTS. See [Configuration](#configuration)
for the listen address and the rest.

Behind a reverse proxy, bind to localhost and let the proxy handle TLS. The proxy
must send `X-Forwarded-Proto` so session cookies are marked `Secure` (trusted from
`127.0.0.1` by default; set `HABENY_FORWARDED_ALLOW_IPS` if the proxy is elsewhere):

```nginx
server {
    listen 443 ssl;
    server_name habeny.example.com;
    ssl_certificate     /etc/ssl/habeny.crt;
    ssl_certificate_key /etc/ssl/habeny.key;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_http_version 1.1;                       # WebSockets (live metrics, console)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```
```bash
# /etc/habeny/habeny.conf
HABENY_TLS=off
HABENY_HOST=127.0.0.1
```

The dev server (`./start.sh --dev`, port 3000) is plain HTTP for development only.

## Authentication

The web UI and the API require signing in. On first start there are no accounts:
open the UI and it asks you to **create the admin account** (with the setup token, see below). After that, the
sign-in page is shown to anyone without a valid session.

- **Account** (sidebar → Settings, or click your username): change your password.
  This signs you out on your other devices.
- **Users** (on the same page, administrators only): add users, change their role,
  reset a user's password (signs them out everywhere) and delete users. You can't delete
  or demote yourself, and there is always at least one administrator.
- **Roles**, enforced by the server on every request:

  | Role | Can |
  |---|---|
  | Viewer | See everything (dashboards, containers, reports, activity); change nothing |
  | Operator | Viewer + deploy/start/stop/delete containers, simulations, log uploads, console, profiles |
  | Admin | Operator + manage users |

  New users are viewers unless you choose otherwise. On upgrade, existing non-admin
  accounts become operators (the access they already had).
- New passwords need 12+ characters (`HABENY_PASSWORD_MIN_LENGTH`), can't be a common
  password or contain the username.
- Sessions are HttpOnly cookies, valid for 7 days (`HABENY_SESSION_TTL_HOURS` to change).
  **Account → Active sessions** lists your sign-ins (device, IP, last seen) and can end
  any of them; admins can sign a user out everywhere from the Users table.
- **Two-factor authentication** (Account → Two-factor): scan a QR code with any
  authenticator app (Google/Microsoft Authenticator, 1Password, Authy…), then sign-in asks
  for the 6-digit code. You get 10 one-time recovery codes for a lost phone; an admin can
  reset 2FA for a user who lost both (Users → Reset 2FA).
- After 10 failed sign-ins from one IP within 15 minutes, further attempts are refused for a while.
- Sign-ins, failed sign-ins, setup and every user-management action are recorded in the Activity log.
- First-run setup needs a one-time **setup token**, so nobody else who can reach the
  server can claim the admin account. It is printed to the log and saved to a file only
  root and the service can read:
  `sudo cat /var/lib/lxc-siem-platform/setup-token` or `journalctl -u habeny | grep "setup token"`.

### Single sign-on (OpenID Connect)

Users can sign in through your identity provider: Microsoft Entra ID, Okta, Google
Workspace, Keycloak, Authentik or anything else that speaks OIDC. Register Habeny as a
web application ("confidential client") with this redirect URI:

    https://<your-habeny-host>:9000/api/auth/oidc/callback

then add these to `/etc/habeny/habeny.conf` (readable only by root and the service, since it
holds the client secret) and `sudo systemctl restart habeny`:

| Variable | Meaning |
|---|---|
| `HABENY_OIDC_ISSUER` | Issuer URL, e.g. `https://login.microsoftonline.com/<tenant-id>/v2.0` (turns SSO on) |
| `HABENY_OIDC_CLIENT_ID` / `HABENY_OIDC_CLIENT_SECRET` | From the app registration |
| `HABENY_OIDC_REDIRECT_URI` | The redirect URI above. Set it when behind a reverse proxy |
| `HABENY_OIDC_ADMIN_GROUPS`, `..._OPERATOR_GROUPS`, `..._VIEWER_GROUPS` | Comma-separated group names/IDs from the `groups` claim. When any is set, the role follows group membership on every sign-in and people in none of them are refused |
| `HABENY_OIDC_DEFAULT_ROLE` | Without group mapping: role for new SSO users (default `viewer`; admins can change it) |
| `HABENY_OIDC_USERNAME_CLAIM` | Claim used as the username (default `preferred_username`, then `email`) |
| `HABENY_OIDC_GROUPS_CLAIM`, `HABENY_OIDC_SCOPES`, `HABENY_OIDC_BUTTON_LABEL`, `HABENY_OIDC_CA_BUNDLE` | Optional: groups claim name (default `groups`), scopes (default `openid profile email`; add `groups` for Keycloak/Authentik), sign-in button text, CA file for a private IdP |

The sign-in page then shows a "Sign in with SSO" button. The first SSO sign-in creates the
account; SSO accounts have no Habeny password, and their two-factor is whatever the identity
provider enforces. An SSO identity never takes over an existing local account with the same
name: that sign-in is refused. Local accounts keep working, so keep one local admin as a
break-glass account. SAML and LDAP aren't supported; most identity providers that offer
them offer OIDC too.

**Stored secrets:** SIEM auth keys and enrollment tokens in manager profiles are encrypted
in the database and never sent back to the browser (only the last 4 characters are shown).
The encryption key is generated on first start at `/var/lib/lxc-siem-platform/secret.key`
(or set `HABENY_SECRET_KEY`). **Back it up together with `platform.db`**: without it, stored
keys can't be read and must be re-entered in each profile.

**Forgotten password:** another administrator can reset it on the Account page. If the only
administrator is locked out, remove all accounts on the server and the UI will offer setup again:

```bash
sudo python3 -c "import sqlite3; c = sqlite3.connect('/var/lib/lxc-siem-platform/platform.db'); c.execute('DELETE FROM sessions'); c.execute('DELETE FROM users'); c.commit()"
```

## Frontend

For development with hot reload: `sudo ./start.sh --dev` (see [Development](#development)).
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
├── deploy/                  # Installer, package/release builds, systemd units, example config
├── start.sh                 # Run from a checkout (development)
├── app/                     # FastAPI application
│   ├── __init__.py          # create_app(): storage init, middleware, routers
│   ├── config.py            # Every setting: type, default, description; config file loading
│   ├── version.py           # The version (releases, UI, API)
│   ├── cli.py               # The `habeny` admin command
│   ├── server.py            # uvicorn with graceful shutdown
│   ├── migrations/          # Versioned database migrations
│   ├── state.py             # In-memory state shared by routes/services
│   ├── middleware.py        # /api prefix stripping, latency tracking
│   ├── db.py                # SQLite database layer
│   ├── helper/              # Privileged LXC helper (root) + client used by the web app
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
pip install -r requirements-dev.txt
ruff check .
ruff format .

# JavaScript (eslint)
cd frontend && npx eslint src/
```

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v

# Without LXC (e.g. on a laptop): use the in-memory python-lxc stand-in
HABENY_LXC_BACKEND=direct PYTHONPATH=tests/stubs python3 -m pytest tests/
```

CI (`.github/workflows/ci.yml`) runs the tests on Python 3.10 and 3.12, the ruff
correctness rules, a frontend build, and `pip-audit` / `npm audit` on every push and pull
request and weekly. Dependabot (`.github/dependabot.yml`) proposes dependency updates.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). It also summarizes how Habeny is
secured. The brief for an independent security review is in
[docs/security-review-scope.md](docs/security-review-scope.md).

## License

Proprietary — Habeny Platform.
