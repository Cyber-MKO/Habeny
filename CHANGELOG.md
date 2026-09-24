# Changelog

Notable changes to Habeny, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/) (see [CONTRIBUTING.md](CONTRIBUTING.md#versions-and-releases)).
The release workflow publishes a version's section here as its release notes.

## [Unreleased]

## [2.2.0] - 2026-09-24

**Upgrading:**
- **A license is now required.** Each install gets a 30-day trial counted from its first
  account, so an install older than that stops accepting new deployments, simulations,
  benchmarks and log uploads when you upgrade, until a license is installed. Viewing and
  managing existing containers keep working. Before upgrading, run
  `sudo habeny license request` and send the server ID to Habeny Platform.
- **OSSIM support is removed.** Existing OSSIM containers keep working and can be deleted.
  Manager profiles that name OSSIM need a different SIEM type.
- Database migrations v0003–v0007 run automatically after a backup, and the old daily
  activity files are imported into the new audit trail. v0006 (teams) can't be undone by
  `habeny db downgrade`; restore the backup taken before it instead.
- Installation and operations documentation moved from the README to `docs/` (start with
  `docs/admin-guide.md`).

### Added
- **API tokens** for scripts and CI (`Authorization: Bearer`): at most the account's
  role, optional expiry, last use recorded; Account → API tokens and
  `habeny token create|list|revoke`. Tokens can't change account settings.
- **Audit trail** in the database: who, token, client IP and request ID for every action.
  Search by action, user, result, dates and text; export to CSV or JSON Lines. It's
  tamper-evident: a hash chain that `habeny audit verify` and Activity → Verify integrity
  check.
- **Monitoring:** `/healthz` and `/readyz` probes (no sign-in) and Prometheus `/metrics`.
  Alerts for low disk space, LXC unavailable, a failed backup, a failed deployment and an
  unreachable host, on the Monitoring page and in the header.
- **Notifications** to Slack, webhooks (optionally HMAC-signed) and email
  (`HABENY_SMTP_*`) when deployments, simulations and benchmarks finish and when alerts
  start or clear.
- **Teams** with container limits per team and per user. Members see only their team's
  containers, simulations and reports.
- **Several LXC hosts under one console:** register other Habeny servers (certificate
  pinning, `habeny tls fingerprint`), switch between them from the sidebar, and see all
  hosts' status on the Hosts page.
- **French** interface, with a translation framework for more languages.
- **Per-server licenses**, checked offline: `habeny license request|install|status` and
  Settings → License. A 30-day trial, then new deployments, simulations, benchmarks and
  log uploads need a license; viewing and managing existing containers always work. See
  Upgrading above.
- `THIRD_PARTY_NOTICES.txt` in every release (and linked from About Habeny): the bundled
  Python and npm packages with their licenses. The build fails on a copyleft or unknown
  license.
- **Customer documentation** in `docs/` (shipped in `/opt/habeny/docs`): requirements and
  sizing, an administrator guide, a user guide, an API guide with examples, a generated API
  reference, and troubleshooting.
- **Support:** `habeny support-bundle` collects diagnostics for a support request (no
  secrets, database or uploaded logs). SUPPORT.md explains how to get help, the severity
  levels and the supported versions; draft support terms are in `docs/legal/`. GitHub issue
  templates are added, and release notes now link the upgrade guide and support.
- Legal and privacy documents: `LICENSE`, a draft EULA, a sourced review of the SIEM
  vendors' licenses and trademarks (`docs/legal/`), and `docs/privacy.md`, which lists
  what Habeny stores, for how long and what it connects to.

### Changed
- The README is now for developers. Installation and operations moved to
  `docs/admin-guide.md`.
- `HABENY_HISTORY_RETENTION_DAYS` now also deletes finished benchmarks and their metrics,
  which were kept forever.
- Confirmations use accessible in-page dialogs instead of the browser's `confirm()`;
  deleting many containers asks you to type "delete".
- Results that showed raw JSON (container details, deploy, simulation and upload
  results, reports, profiles) are now shown as labelled values and tables.
- Accessibility (checked with axe-core on every page): labelled controls, landmarks and
  headings, WCAG AA contrast, visible focus, announced messages.
- Small screens: the sidebar becomes a menu, and tables scroll within their card.

### Removed
- **OSSIM support.** AlienVault OSSIM was retired at the end of 2024, and Habeny's installer
  depended on a download that no longer exists. New deployments, manager profiles and
  config templates can't use it. Containers deployed with it earlier are still listed and
  can be stopped and deleted. A manager profile that names OSSIM now gets a clear error
  on deploy: change its SIEM type.

### Fixed
- A benchmark that crashed was recorded as completed.
- Bulk operations listed all containers once per container.

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

[Unreleased]: https://github.com/Cyber-MKO/Habeny/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/Cyber-MKO/Habeny/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Cyber-MKO/Habeny/releases/tag/v2.1.0
