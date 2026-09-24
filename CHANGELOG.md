# Changelog

Notable changes to Habeny, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/) (see [CONTRIBUTING.md](CONTRIBUTING.md#versions-and-releases)).
The release workflow publishes a version's section here as its release notes.

## [Unreleased]

## [2.1.0] - 2026-09-24

The first tagged release. It covers everything since the original import (2.0.0), which was
never tagged. **Upgrading from 2.0.0:** install with `deploy/install.sh` or the `.deb`. The
database is migrated automatically after a backup. The first visit asks for the one-time
setup token (in `/var/lib/lxc-siem-platform/setup-token`) to create the admin account.

### Security
- Sign-in is required for the whole UI and API. The first admin account can only be
  created with a one-time setup token from the server.
- Roles: viewer, operator and admin.
- Password policy (length, common-password list); lists of active sessions that users can
  end; two-factor authentication (TOTP with recovery codes); single sign-on with OpenID
  Connect.
- HTTPS by default (a self-signed certificate, or your own).
- The web app runs as an unprivileged user; only a small root helper talks to LXC.
- Request values are never run as shell or used as host paths; the SPA file server
  refuses path traversal.
- SIEM auth keys are encrypted at rest and never returned by the API.
- CORS is an explicit allowlist (`HABENY_CORS_ORIGINS`) instead of allow-all.
- Dependencies with known vulnerabilities upgraded. SECURITY.md, Dependabot, and a weekly
  `pip-audit` / `npm audit`.
- Backups are unpacked with tarfile's `data` filter as well as Habeny's own checks.

### Added
- Account page: change your password, manage users, 2FA and sessions.
- Live deployment activity on the Deploy page.
- Configuration in `/etc/habeny/habeny.conf`, checked at startup, with `habeny config`
  showing each setting and where it comes from.
- Versioned database migrations (`habeny db status|migrate|backup|restore|downgrade`) that
  back the database up before changing it.
- Full backups of data, keys and configuration, on a schedule or on demand
  (`habeny backup create|list|verify|restore`, or the Account page).
- Retention for activity, metrics, reports and finished jobs (`habeny prune`, and hourly).
- Request IDs in every log line and error response; JSON logs (`HABENY_LOG_FORMAT=json`);
  an optional rotated log file.
- Deployment progress, simulations and other job state survive a restart.
- A single-instance guard. The scaling limits are documented.
- Packaging: a `.deb`, a release tarball with the frontend prebuilt, offline wheels, and a
  Release button (Actions → Release → Run workflow).
- `start.sh` quick start that also builds and serves the frontend.

### Changed
- Graceful shutdown: running deployments finish, and background work stops cleanly.
- Faster Dashboard and System pages; `/agents` no longer blocks the server while listing.
- `install.sh` installs a copy to `/opt/habeny` and leaves the checkout alone.
- React 19 and Vite 8; FastAPI and Pydantic v2 APIs throughout (no deprecation warnings).
- The version lives only in `app/version.py`.
- The deployment `parallel_mode` option now works: `multiprocessing` (default),
  `sequential` or `threading`. It used to be ignored.
- Code split from `main.py`, `utils.py` and `models.py` into the `app/` package.

### Fixed
- Attack and syslog simulations targeted every running container, whatever the
  selector said. They now honour the chosen containers, status, SIEM type, group, tags
  and count.
- Stopping an attack simulation now stops it.
- "database is locked" errors during large deployments.
- Pydantic v2 startup error.
- Reloading a page whose path is also an API path.

### Removed
- `index.legacy.html` and `mailmap.txt`.

### Development
- CI on every push and pull request:
  - Python tests on 3.10 and 3.12, with deprecation warnings as errors and a coverage
    floor
  - ruff with its full configuration, and ESLint 9 (flat config)
  - Vitest frontend tests
  - shellcheck and a package build
  - an integration workflow that installs Habeny on a real Ubuntu runner and deploys a real
    LXC container
- A changelog, and a versioning and commit policy (CONTRIBUTING.md).

## [2.0.0] - 2026-07-05

The original import (untagged): LXC container deployment with Wazuh, OSSEC, OSSIM,
UTMstack and Elastic agents, attack and syslog simulations, benchmarks, reports and a
React UI.

[Unreleased]: https://github.com/Cyber-MKO/Habeny/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/Cyber-MKO/Habeny/releases/tag/v2.1.0
