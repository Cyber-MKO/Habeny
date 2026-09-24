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
| **UTMstack** | utmstack_agent_service | Auth key enrollment |
| **Elastic** | elastic-agent | Fleet enrollment token |
| **None** | — | Bare container (no agent) |

Habeny doesn't ship these agents: when you deploy, your server downloads each one from its
publisher (or, for UTMstack, from your UTMstack server), under the publisher's license.
See [docs/legal/siem-vendors.md](docs/legal/siem-vendors.md). The names are trademarks of
their owners.

## Documentation

This README is for developers. Customers and administrators should start with the
[documentation index](docs/README.md):

- [Requirements and sizing](docs/requirements.md): supported systems, network, sizing
- [Administrator guide](docs/admin-guide.md): installing, HTTPS, configuration, users and
  SSO, licensing, backups, upgrades, monitoring, several hosts
- [User guide](docs/user-guide.md): deploying, simulations, benchmarks, reports
- [API guide](docs/api.md) and [API reference](docs/api-reference.md)
- [Troubleshooting](docs/troubleshooting.md) and [Support](SUPPORT.md)

Quick start on a test server: `sudo apt install ./habeny_<version>_all.deb`, open
`https://<host>:9000` and follow the setup (the admin guide has the details).

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

## Languages and accessibility

The interface is available in **English and French** (Account → Language, or on the
sign-in page; the default follows the browser). Messages from the server stay in English.
Adding a language means translating `frontend/src/i18n/fr.json` into a new file and
listing it in `frontend/src/i18n/index.js`. `npm test` fails if any interface text lacks a
translation.

Accessibility is checked with axe-core on every page, at desktop and phone width (see
[docs/accessibility.md](docs/accessibility.md)):

- every control is labelled
- dialogs keep keyboard focus
- messages are announced to screen readers
- contrast meets WCAG AA
- the layout works down to phone width, with the sidebar as a menu

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
├── docs/                    # Accessibility, privacy, legal drafts (EULA, SIEM vendors)
├── tools/license_tool.py    # Vendor only: signing keys and license files (not shipped)
├── LICENSE                  # Proprietary license notice
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
│   └── models/              # Pydantic models by domain (import from app.models)
├── requirements.txt         # Python dependencies
├── ruff.toml                # Python linter config (ruff)
│
├── frontend/                # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx          # Router, layout, sidebar
│   │   ├── api.js           # API client
│   │   ├── ws.js            # WebSocket hook for live metrics
│   │   ├── store.jsx        # Global state context
│   │   ├── pages/           # Page components
│   │   └── components/      # Reusable UI components
│   └── eslint.config.js     # JavaScript linter config
│
├── tests/                   # Test suite
│   ├── test_db.py           # Database layer tests
│   ├── test_models.py       # Model validation tests
│   └── test_core_shell.py   # Shell command tests
```

## API

See the [API guide](docs/api.md) (authentication, errors, examples) and the generated
[API reference](docs/api-reference.md). After changing routes or request models,
regenerate the reference: `PYTHONPATH=tests/stubs python3 deploy/api_reference.py` (a test
fails when it's out of date).

## Linting

```bash
pip install -r requirements-dev.txt
ruff check .                      # Python (config: ruff.toml)
cd frontend && npx eslint .       # JavaScript (config: frontend/eslint.config.js)
```

CI runs both on every pull request, and both must be clean.

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v

# Without LXC (e.g. on a laptop): use the in-memory python-lxc stand-in, with coverage
HABENY_LXC_BACKEND=direct PYTHONPATH=tests/stubs python3 -m pytest tests/ --cov=app

# Frontend (Vitest + Testing Library)
cd frontend && npm test
```

`tests/integration/smoke.sh` is an end-to-end check of an installed Habeny against real
LXC: it creates the first admin, deploys an Ubuntu container, stops, starts and deletes it,
takes and verifies a backup, and restarts the service. Run it as root on a disposable
machine right after `deploy/install.sh`.

CI runs on every push and pull request:

- `.github/workflows/ci.yml`: the Python tests on 3.10 and 3.12, with deprecation
  warnings as errors and a coverage floor; ruff; ESLint, the frontend tests and build;
  shellcheck and a package build; `pip-audit` / `npm audit` (also weekly)
- `.github/workflows/integration.yml`: installs Habeny on an Ubuntu 24.04 runner and runs
  `tests/integration/smoke.sh` against real LXC

Dependabot (`.github/dependabot.yml`) proposes dependency updates.

## Contributing and releases

[CONTRIBUTING.md](CONTRIBUTING.md) covers pull requests, commit messages, versioning
(SemVer; the version lives in `app/version.py`) and how to publish a release.
[CHANGELOG.md](CHANGELOG.md) lists what changed in each version.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). It also summarizes how Habeny is
secured. The brief for an independent security review is in
[docs/security-review-scope.md](docs/security-review-scope.md).

## Licensing

Habeny is proprietary software of Habeny Platform: see [LICENSE](LICENSE) and the
[EULA](docs/legal/EULA.md) (a draft awaiting legal review). It includes open-source
packages under their own licenses; release builds list them, with their license texts, in
`THIRD_PARTY_NOTICES.txt`, also linked from **About Habeny** in the UI.

### License keys

Customers: see [Licensing](docs/admin-guide.md#licensing) in the administrator guide.

**Licensing is on in every build**, including installs from a git checkout, because
`app/licensing_key.py` holds Habeny Platform's public key. (With that list empty, licensing
is off and the License page says a license isn't required.) The vendor keeps the matching
private key offline, encrypted with a passphrase (`HABENY_LICENSE_KEY_PASSWORD`), and
issues licenses with `tools/license_tool.py sign`. For development, run the trial or issue
yourself a license for the dev machine. The private key must never be committed (`*.pem` is
ignored). Release builds leave `tools/` out.

Like any offline check, this keeps honest customers honest. Someone with root and the
source can remove it; the EULA covers that.

### Third-party licenses

`deploy/third_party_notices.py` writes `THIRD_PARTY_NOTICES.txt` from the Python packages
of `requirements.txt` (with all their dependencies) and the npm packages bundled into the
frontend. `deploy/build-release.sh` runs it, so every release carries a current list. It
also **enforces the license policy**: the build, the Python tests and the frontend CI job
fail on a copyleft (GPL, AGPL, SSPL…), source-available (Elastic, BUSL) or unknown license,
so a Dependabot update can't bring one in unnoticed. LGPL is allowed for Python packages.
`python3 deploy/third_party_notices.py --summary` prints the current list.
