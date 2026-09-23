# Independent security review: scope

This is the brief for an outside firm doing a penetration test and a source-code review
of Habeny. Share it when requesting quotes. It says what Habeny is, what matters most,
what to test, and what we expect back.

## 1. What Habeny is

Habeny is a web application that creates and manages many LXC containers on one Linux
host. Each container runs a SIEM agent (Wazuh, OSSEC, Elastic, UTMStack, AlienVault
OSSIM), and Habeny simulates activity in them for testing and benchmarking.

- **Backend:** Python 3.10+, FastAPI and uvicorn, SQLite. It runs as the unprivileged
  `habeny` user under systemd.
- **Privileged helper:** `habeny-helper` runs as root. It exposes an allowlisted subset of
  the LXC API over a Unix socket, and only the `habeny` user may connect.
- **Frontend:** React single-page app, served by the backend.
- **Deployment:** `deploy/install.sh` sets up systemd units. HTTPS is on by default.
- **Size:** about 75 Python modules and 25 React components. See the README's project
  structure.

## 2. What we want to protect

| Asset | Why it matters |
|---|---|
| Root on the host | The helper runs as root. Any way from the web app, or the `habeny` user, to root, arbitrary LXC config, or host files is critical |
| Container isolation | Containers must not reach the host or each other beyond what the network config allows |
| Accounts and roles | Viewers must not change anything; operators must not manage users; nobody may act without signing in |
| SIEM credentials | Auth keys and enrollment tokens stored in manager profiles; they give access to customers' SIEM servers |
| Integrity of test results | Benchmarks and reports inform purchasing and tuning decisions |

## 3. Attacker positions to test from

1. **Network, no account.** Can reach the HTTPS port and nothing else.
2. **Viewer account.** Read-only role.
3. **Operator account.** Can deploy and delete containers, run simulations, and use the
   in-container console (a root shell *inside* the container).
4. **Code running inside a managed container.** For example, a compromised SIEM agent.
5. **The `habeny` service user.** For example, after a web-app compromise. The question
   is what the helper lets it do.

## 4. In scope, by priority

### Critical

- **Privileged helper** (`app/helper/server.py`, `protocol.py`, `client.py`):
  - the allowlist of operations and LXC config and cgroup keys
  - argument validation and peer-credential checks
  - file-descriptor passing for the console
  - `lxc-attach` command construction
  - Try to escalate from the `habeny` user to root, or to write arbitrary LXC config (hooks,
    mounts, AppArmor, devices).
- **Command execution inside containers:**
  - `app/core/shell.py`, `app/core/container.py` and `app/installers/*`: SIEM
    installers built from user input (manager IP, auth keys, group names).
  - `app/simulation/*`, `app/routes/logs.py` and log upload: file paths and content.
  - Look for injection into shell commands and path traversal.
- **Container console** (`app/routes/console.py`, WebSocket): authorization, origin
  checks, and whether it can be steered to a container the user shouldn't reach, or to
  the host.

### High

- **Authentication and sessions:**
  - `app/services/auth.py`, `app/routes/auth.py` and `app/routes/users.py`.
  - First-run setup token, login rate limiting, and session fixation and revocation.
  - Role checks on every route and WebSocket: `require_access` in
    `app/services/auth.py` and router registration in `app/routes/__init__.py`.
- **Two-factor authentication** (`app/services/totp.py`): bypass of the second step,
  replay, brute force of codes and recovery codes, and enrolment without the password.
- **Single sign-on (OIDC)** (`app/services/oidc.py`):
  - state and nonce handling, PKCE, ID token validation
  - account linking (it must never take over a local account by name)
  - group-to-role mapping, and login CSRF
- **Secrets at rest** (`app/core/secrets.py`): key handling, and whether any API
  response, log or export leaks a decrypted secret.

### Medium

- **Input validation** (`app/core/validation.py`, `app/models/*`): container names,
  IPs, SIEM parameters, config import (`/configs/import`).
- **Browser-side:** XSS in the React UI (container output, activity log, reports),
  CSRF (cookies are SameSite=Strict, and CORS is off unless an allowlist is configured),
  clickjacking, and the SPA and `/api` routing in `app/middleware.py`.
- **Reports** (`app/services/reporting.py`): PDF and CSV generation from untrusted
  container data, including CSV formula injection.
- **Installer and systemd units** (`deploy/`): file permissions, sandboxing options,
  and secrets in `/etc/default/habeny`.
- **Denial of service with an account:** for example, deploying or simulating enough
  to take the host down. Tell us about gaps in the limits; flooding tests are not wanted.

## 5. Out of scope

- The SIEM agents and servers themselves, LXC, the kernel, and the host OS packages.
- Social engineering and physical access.
- Volumetric denial of service.
- Third-party identity providers. The integration with them is in scope.

## 6. Test environment we'll provide

- An Ubuntu 22.04 or 24.04 VM (4 vCPU, 8 GB RAM) with Habeny installed by
  `deploy/install.sh`. It has HTTPS with a self-signed certificate, and LXC with a
  bridge.
- One account per role: viewer, operator and admin. One of them has 2FA enabled.
- An OIDC test provider (Keycloak) configured for SSO, with group mapping.
- A few deployed containers, and manager profiles with dummy SIEM credentials.
- SSH access as an unprivileged user, and on request as the `habeny` user, to test
  positions 4 and 5.
- Read access to this repository at the commit under test.

## 7. Approach we expect

- A **grey-box** penetration test of the running system from each position in section 3.
- A **manual source review** of the critical and high areas, supported by static
  analysis.
- A check of dependencies. CI already runs `pip-audit` and `npm audit`; we want to know
  anything they miss.
- Rough effort: **8–12 person-days**. We welcome the firm's own estimate.

## 8. Deliverables

1. A report with, for each finding:
   - a severity (CVSS v3.1 or v4)
   - the affected component and commit
   - reproduction steps
   - impact from a real attacker position
   - a recommended fix
2. An executive summary for non-technical readers.
3. **A free retest** of fixed findings within 60 days, and an updated report stating
   which findings are resolved.
4. Critical findings reported **immediately** (within 24 hours of discovery), not only
   in the final report.

## 9. Known limitations (no need to report)

- The self-signed certificate warning in the default install. Your own certificate or
  a reverse proxy is documented.
- The in-container console gives operators a root shell *inside* containers by design.
  Escaping to the host is in scope.
- SAML and LDAP are not supported, only OIDC and local accounts.
- Pending 2FA sign-in challenges and pending SSO sign-ins are kept in memory, not in the
  database. Sessions are stored in the database. The app is designed to run as a single
  process.
