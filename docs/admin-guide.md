# Administrator guide

For the people who install and run Habeny: installing, securing, configuring, users,
licensing, backups, upgrades and monitoring. For using the interface, see the
[user guide](user-guide.md). For what the server needs, see [requirements.md](requirements.md).

## Contents

- [Installing](#installing)
- [Running and stopping](#running-and-stopping)
- [HTTPS](#https)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Licensing](#licensing)
- [Backups](#backups)
- [Upgrading and rolling back](#upgrading-and-rolling-back)
- [Monitoring and alerts](#monitoring-and-alerts)
- [Notifications](#notifications)
- [Logs](#logs)
- [Audit trail](#audit-trail)
- [Data retention](#data-retention)
- [Checking detections](#checking-detections)
- [Several LXC hosts](#several-lxc-hosts)
- [Security checklist](#security-checklist)
- [Getting help](#getting-help)

## Installing

Check [requirements.md](requirements.md) first: a supported OS, enough memory and disk for
the containers you plan, and root access.

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
sudo apt install ./habeny_<version>_all.deb       # e.g. habeny_2.2.0_all.deb
```

**Release tarball** (any systemd distribution with apt)

```bash
tar xzf habeny-<version>.tar.gz && cd habeny-<version>
sudo ./deploy/install.sh
```

**From a git checkout** (builds the frontend, so it needs Node.js 20.19+/22.12+)

```bash
git clone https://github.com/Cyber-MKO/Habeny.git && cd Habeny
sudo ./deploy/install.sh
```

Then open `https://<host>:9000` (see [HTTPS](#https)); the first visit asks for the setup
token (see [Authentication](#authentication)). Then install a license
([Licensing](#licensing)); until you do, Habeny runs as a 30-day trial. What gets installed:

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
`sudo mkdir -p /opt/habeny && sudo tar xzf habeny-wheels-<version>-cp312-x86_64.tar.gz -C /opt/habeny`.

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
| `HABENY_SHUTDOWN_TIMEOUT` | `600` | Seconds a stop/restart waits for running deployments to finish before interrupting them (the systemd unit allows up to 840) |
| `HABENY_LOG_LEVEL` | `INFO` | Log level |
| `HABENY_LOG_FORMAT` | `text` | `text`, or `json` (one object per line, for log collectors) |
| `HABENY_LOG_FILE` |  | Also write logs to this file, rotated by size (stdout always gets them; under systemd that's the journal) |
| `HABENY_LOG_MAX_MB` | `50` | Rotate the log file at this size (MB) |
| `HABENY_LOG_BACKUPS` | `5` | Rotated log files to keep |
| `HABENY_DEPLOY_WORKERS` | CPU count | Containers deployed in parallel (default: CPU count) |
| `HABENY_BENCHMARK_WORKERS` | CPU count | Parallel workers for benchmark runs (default: CPU count) |
| `HABENY_METRICS_SAMPLE_SECONDS` | `60` | How often the system metrics shown in history charts are saved (seconds) |
| `HABENY_METRICS_RETENTION_DAYS` | `30` | Keep system and API-latency samples this many days (0: forever) |
| `HABENY_HISTORY_RETENTION_DAYS` | `365` | Keep the activity log (audit trail), deployment results, finished jobs and benchmarks this many days (0: forever) |
| `HABENY_REPORT_RETENTION_DAYS` | `0` | Delete generated report files after this many days (0: keep) |
| `HABENY_BACKUP_INTERVAL_HOURS` | `24` | Take a full backup this often (hours; 0: no scheduled backups) |
| `HABENY_BACKUP_KEEP` | `14` | Full backups to keep (the oldest are deleted) |
| `HABENY_BACKUP_DIR` |  | Where full backups go (default: `DATA_DIR/backups`). Outside the data directory, also allow it in systemd (see the admin guide, Backups) |
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
| `HABENY_PUBLIC_URL` |  | This server's address as users reach it (e.g. `https://habeny.example.com`), for links in notifications |
| `HABENY_ALERT_DISK_PERCENT` | `10` | Alert when free space for data or containers falls below this percentage (0: off) |
| `HABENY_SMTP_HOST` |  | Mail server for email notifications (empty: email off) |
| `HABENY_SMTP_PORT` | `587` | Mail server port |
| `HABENY_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (implicit TLS, usually port 465) or `off` |
| `HABENY_SMTP_USER` |  | Mail server user name (empty: no login) |
| `HABENY_SMTP_PASSWORD` |  | Mail server password |
| `HABENY_SMTP_FROM` |  | Sender address (default: habeny@<host name>) |
| `HABENY_DETECTION_DELAY_SECONDS` | `120` | After an attack simulation, wait this long for the SIEM to index its alerts before checking what it detected (seconds) |
| `HABENY_DATA_DIR` | `/var/lib/lxc-siem-platform` | Database, keys, reports and logs *(set by the installer)* |
| `HABENY_LXC_BACKEND` |  | `helper` (unprivileged app + root helper) or `direct` (app runs as root); default: direct when root, else helper *(set by the installer)* |
| `HABENY_HELPER_SOCKET` | `/run/habeny/helper.sock` | The helper's Unix socket *(set by the installer)* |
| `HABENY_HELPER_USER` | `habeny` | The only user (besides root) the helper accepts *(set by the installer)* |

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

### API tokens

Scripts, CI pipelines, Prometheus and other Habeny consoles use **API tokens**:

```bash
curl -H "Authorization: Bearer hby_…" https://habeny.example.com:9000/api/agents
```

Create them under **Account → API tokens**, or on the server with
`sudo habeny token create USER NAME [--role viewer] [--expires-days 90]`. A token:

- acts as its user, with at most that user's role; demoting the user limits it too
- can't change account settings: password, two-factor, sessions and tokens need a browser
  sign-in
- expires after 90 days by default
- is shown once; only a hash is stored

**Last used** shows when and from where each token was used. What was done with a token is
recorded in the audit trail with its name. Admins see and revoke everyone's tokens.

### Teams and limits

Admins create teams on the **Teams** page to separate teams or customers:

- Members of a team see and manage **only their team's containers**, simulations and
  reports. Another team's container reads as "not found".
- People without a team see the containers that belong to no team, so an install without
  teams behaves as before. Admins see everything.
- Containers belong to the team of the person who deploys them. Existing ones can be moved
  between teams on the Teams page.
- **Limits:** a team's container limit caps its total; a personal limit caps what one user
  creates. Both are checked before deployments and benchmarks.

SIEM targets (manager profiles), groups and config templates are shared by everyone. The
host-wide dashboard figures (CPU, memory) stay visible to all.

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

## Licensing

Each server needs a license from Habeny Platform. A new install runs as a **30-day trial**,
counted from its first account.

```bash
sudo habeny license request          # prints this server's ID: send it to Habeny Platform
sudo habeny license install FILE     # or Settings → License → Install license (admins)
sudo habeny license status           # exit status 1 when new work is refused
```

- A license is for one server (its ID comes from `/etc/machine-id`), has an expiry date or
  none, and may limit the number of containers.
- From 30 days before it expires, and during a **14-day grace period** after, a warning
  shows in the header and a `license` alert goes to your notification channels.
- Without a valid license (trial over, expired past the grace period, or a license for
  another server), Habeny refuses **new work**: deployments, simulations, benchmarks and
  log uploads. Everything stays viewable, and existing containers can still be started,
  stopped, deleted and used from the console, so nothing is held hostage.
- **Moving to another machine**, or cloning a VM, changes the server ID: ask for a new
  license. (A cloned VM keeps its source's machine ID until you run
  `systemd-machine-id-setup`; do that on clones.)
- The license is checked offline; Habeny never contacts Habeny Platform. Backups include
  the license file.

## Backups

Habeny takes a **full backup** every day (`HABENY_BACKUP_INTERVAL_HOURS`) and keeps the
newest 14 (`HABENY_BACKUP_KEEP`) in `/var/lib/lxc-siem-platform/backups/`. Each is one
`habeny-backup-<date>-<time>-<type>.tar.gz` holding:

- the database (a consistent copy taken while Habeny runs)
- `secret.key`, which decrypts the stored SIEM keys
- reports, config templates, container metadata and the activity log
- the TLS certificate and `habeny.conf`
- a manifest with a checksum for every file

It doesn't include the package cache, which is downloaded again when needed.

```bash
sudo habeny backup create          # one now (also: Account → Backups → Back up now)
sudo habeny backup list
sudo habeny backup verify FILE     # complete and undamaged?
```

Admins can also download backups from **Account → Backups**. **Keep copies off the server.**
Either download them, or point `HABENY_BACKUP_DIR` at a mounted share. That directory is
outside the data directory, so the sandboxed service also needs permission to write there:

```bash
sudo systemctl edit habeny         # add these two lines, save, then restart habeny
[Service]
ReadWritePaths=/mnt/backups/habeny
```

A backup contains the encryption key and every stored secret, so protect it like a password
vault (the files are created `0600`).

**Restoring** (the same or a new server; install Habeny first):

```bash
sudo systemctl stop habeny
sudo habeny backup restore habeny-backup-20260924-020000-scheduled.tar.gz
sudo systemctl start habeny
```

The restore checks every file's checksum before changing anything, and it keeps what it
replaces (`*.before-restore`, and the old database under `backups/`). A backup's settings
come back as `restored-habeny.conf` for you to compare with `/etc/habeny/habeny.conf`.
A backup from a newer Habeny can't be restored into an older one.

## Upgrading and rolling back

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

## Monitoring and alerts

| Endpoint | Sign-in | Use |
|---|---|---|
| `GET /api/healthz` | no | Liveness: 200 while the process answers |
| `GET /api/readyz` | no | Readiness: 200 when the database, LXC and the data disk are fine, else 503 |
| `GET /api/metrics` | API token (viewer is enough) | Prometheus metrics |

Metrics include containers by state, deployments and deployed containers by result, running
deployments and simulations, HTTP requests and a latency histogram, free disk space for
data and containers, database size, the newest backup's time, active alerts, users,
sessions, API tokens, host load and memory. Scrape configuration:

```yaml
scrape_configs:
  - job_name: habeny
    scheme: https
    tls_config: {insecure_skip_verify: true}   # only with Habeny's self-signed certificate
    authorization: {credentials_file: /etc/prometheus/habeny.token}
    static_configs: [{targets: ["habeny.example.com:9000"]}]
```

The **Monitoring** page has example alerting rules. Habeny also raises its own alerts,
shown on that page and in the header, and sent to notification channels:

| Alert | When |
|---|---|
| Low disk space | Free space for data or containers under `HABENY_ALERT_DISK_PERCENT` (10%); critical under half of it |
| LXC unavailable | Container operations can't reach LXC (e.g. the helper is down) |
| Backup failed | The last scheduled backup failed |
| Deployment failed | The last deployment had failures; clears after one that fully succeeds |
| Host unreachable | Another Habeny server managed from this console doesn't answer |

## Notifications

Admins add channels on the **Notifications** page:

- **Slack**, or anything that takes Slack incoming webhooks (Mattermost, Rocket.Chat…)
- **Webhook:** a JSON POST: `{"event", "level", "title", "text", "fields", "link", "time",
  "server"}`. With a secret set, `X-Habeny-Signature: sha256=<HMAC-SHA256 of the body>`
  proves it came from Habeny.
- **Email:** through the mail server in `HABENY_SMTP_*` (host, port, `starttls`/`ssl`,
  user, password, sender).

Each channel picks its events: deployments, simulations and benchmarks finishing, alerts
starting and clearing. It can be limited to problems (warnings and errors). Delivery happens
in the background with retries. **Test** sends a message now, and the page shows each
channel's last delivery and error. `HABENY_PUBLIC_URL` makes the links in messages point at
your address. URLs and secrets are stored encrypted and never shown again in full.

## Logs

- **Server log:** stdout, which is the journal under systemd (`journalctl -u habeny -f`; the
  journal rotates it). `HABENY_LOG_FILE` adds a file, rotated at `HABENY_LOG_MAX_MB`.
  `HABENY_LOG_FORMAT=json` writes one JSON object per line for log collectors (Loki, ELK,
  Splunk, ...).
- **Request IDs:** every request gets an ID. It's returned in the `X-Request-ID` header,
  printed on every log line the request causes, and recorded in its activity-log entry.
  Server errors show it to the user, so "request ID 3f9a…" leads straight to the log lines:
  `journalctl -u habeny | grep 3f9a…`. A valid `X-Request-ID` from a reverse proxy is kept,
  which links its logs with Habeny's.
- **Access log:** one line per request with method, path, status, duration and user.
- **Activity log:** the audit trail of what users did, on the Activity page (see below).

## Audit trail

Every action (deployments, deletions, sign-ins, user and token changes, settings) is
recorded in the database with who did it, the API token if one was used, the client IP and
the request ID. The **Activity** page searches it by action, user, result, date range and
text, and exports what matches as CSV or JSON Lines.

It's tamper-evident: each entry stores the SHA-256 of the previous entry's hash and its own
content, and the database refuses to update entries. Checking the chain shows the first
entry that was changed, removed or reordered:

```bash
sudo habeny audit verify                          # or Activity → Verify integrity (admins)
sudo habeny audit export --since 2026-09-01 --format csv > audit.csv
```

Someone with root on the server could still rewrite the whole chain. For evidence that
survives that, ship the server log off the machine: each entry's hash is also logged
(logger `habeny.audit`), so the shipped copy shows what the chain looked like. Entries older
than `HABENY_HISTORY_RETENTION_DAYS` are pruned; the last pruned entry is kept as the
anchor the rest is verified from. On upgrade, the old daily `activity_*.json` files are
imported.

## Data retention

A background task prunes old data hourly, so the disk doesn't fill up over time
(`sudo habeny prune` runs it now):

| Data | Kept | Setting |
|---|---|---|
| System metrics (saved once a minute) and API latency samples | 30 days | `HABENY_METRICS_RETENTION_DAYS` |
| Audit trail (activity log), deployment results, finished jobs, benchmarks | 365 days | `HABENY_HISTORY_RETENTION_DAYS` |
| Generated report files | forever | `HABENY_REPORT_RETENTION_DAYS` |
| Full backups | newest 14 | `HABENY_BACKUP_KEEP` |
| Expired sign-in sessions and API tokens | removed | |

`0` keeps data forever. System metrics are recorded once per `HABENY_METRICS_SAMPLE_SECONDS`
however many dashboards are open. They used to be recorded per viewer every 5 seconds,
about 13 MB per open dashboard per day, kept forever.

What Habeny stores (including uploaded logs), where, for how long and what it connects
to is listed in [docs/privacy.md](privacy.md). Habeny sends no telemetry or crash
reports anywhere.

Simulations, reports, deployments, log schedules and config templates are stored in the
database, so a restart doesn't lose them. Anything that was running when Habeny stopped
is shown as **interrupted**, and log schedules resume by themselves for the time they had
left. Interrupted deployments and simulations aren't restarted automatically: a
half-created container needs deleting first, and an attack simulation replayed hours
later would muddy SIEM test results.

## Checking detections

After an attack simulation, Habeny can ask the SIEM which alerts it raised (see the
[user guide](user-guide.md#checking-what-the-siem-detected)). It uses the SIEM's
Elasticsearch-compatible search API, read-only. Set it up per SIEM, as an admin, on the
SIEM target (Fleet → SIEM Targets → Edit → **Detection API**):

| SIEM | Search API URL | Account needs to read |
|---|---|---|
| Wazuh | the Wazuh indexer, usually `https://<indexer>:9200` | `wazuh-alerts-*` |
| Elastic | Elasticsearch, usually `https://<host>:9200` | `.alerts-security.alerts-*` and `logs-*` |

- Use a dedicated read-only account. For Wazuh, create an indexer user with a role that can
  read `wazuh-alerts-*` (for example in the Wazuh dashboard: Indexer management → Security).
  For Elastic, a user with a read role on those indices, or an **API key** (leave the user
  name empty and paste the key in its base64 form).
- **Test detection connection** checks the URL and credentials. The Wazuh indexer
  usually has a self-signed certificate: the test shows its SHA-256 fingerprint; check it
  (e.g. `openssl s_client -connect indexer:9200 </dev/null | openssl x509 -noout -fingerprint -sha256`)
  and **Trust this certificate**. From then on, connections must present that certificate.
- The password or API key is stored encrypted, like SIEM auth keys, and never shown again.
  Only admins can set or change the connection, because it makes this server connect to
  that address with those credentials. Operators can use it for their simulations.
- The Habeny server must reach the search API (TCP 9200 by default).
- `HABENY_DETECTION_DELAY_SECONDS` (default 120) is how long Habeny waits after a run for the
  SIEM to index its alerts. Raise it for a busy SIEM; a check can always be run again later.
- What is stored: per simulation, the rule ids, names, levels and counts, and per container
  whether and when it was detected. No event contents are copied from the SIEM.

## Several LXC hosts

Each LXC host runs its own Habeny. To manage several from one console:

1. On the other host, create an API token for this console (**Account → API tokens**,
   operator role for full control).
2. Here, go to **Hosts → Add host** and enter its address and the token. With Habeny's
   self-signed certificate, the console shows the certificate fingerprint. Check it matches
   `sudo habeny tls fingerprint` on that host before confirming. From then on, connections
   must present that certificate (pinning). A certificate from a trusted CA is verified
   normally.
3. Pick the host in the **Server** menu at the top of the sidebar, or on the Hosts page.
   Every page then works on that host: containers, deployments, simulations, reports, live
   metrics and the container console. A banner shows which host you're on.

The console relays the API calls and WebSockets with that host's token. Your role on this
console still limits what you can do: a viewer here can only read, whatever the token
allows. Accounts, tokens, teams, notifications and backups stay separate on each server. A
host can be limited to one team. The Hosts page shows every host's status, version,
containers and alerts, and an unreachable host raises an alert.

## Security checklist

After installing:

- [ ] Replace the self-signed certificate with your own, or put Habeny behind your reverse
      proxy ([HTTPS](#https)).
- [ ] Limit who can reach port 9000 with your firewall. The UI and API need no other
      inbound port; see [privacy.md](privacy.md#outbound-connections) for outbound.
- [ ] Turn on two-factor authentication for every admin, or use single sign-on with MFA.
- [ ] Give people the least role they need: viewer, operator or admin.
- [ ] Keep a copy of the backups off the server ([Backups](#backups)). They contain the
      encryption key and every stored secret, so store them like a password vault.
- [ ] Send alerts somewhere people look ([Notifications](#notifications)).
- [ ] Give API tokens an expiry date, and revoke the ones you no longer use.
- [ ] Remember that containers are privileged LXC containers and that the console gives
      operators root inside them. Run Habeny on a host dedicated to testing.

## Getting help

1. Check [troubleshooting.md](troubleshooting.md).
2. Create a support bundle, then send it with your request (see [SUPPORT.md](../SUPPORT.md)):

   ```bash
   sudo habeny support-bundle        # writes /tmp/habeny-support-<host>-<time>.tar.gz
   ```

   It holds diagnostics only: versions, service states, settings with secrets hidden,
   database and license state, disk space and the end of the log file. It never includes
   passwords, keys, the license file, the database or uploaded logs. Look through it
   before sending it, because the log excerpt can name users, IPs and containers.
