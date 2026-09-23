# Security Policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems.

Report privately through GitHub: on the repository page open **Security → Report a
vulnerability** (GitHub private vulnerability reporting). Include:

- what an attacker can do, and what access they need first (network access only, a
  viewer account, an operator account, a shell on the host, ...)
- steps to reproduce, and the Habeny version or commit
- any logs, requests or proof-of-concept code

What to expect:

| | Target |
|---|---|
| Acknowledgement | within 3 working days |
| First assessment (confirmed or not, severity) | within 10 working days |
| Fix for critical/high severity | within 30 days, sooner when actively exploited |
| Fix for medium/low severity | next regular release |

We'll keep you informed, agree on a disclosure date with you (normally when the fix is
released, at most 90 days after the report), and credit you in the advisory unless you
ask us not to.

## Supported versions

Security fixes go into the latest release on `main`. Upgrade with `git pull` and
`sudo ./deploy/install.sh`.

## Scope

In scope: this repository's code (the web app, the privileged LXC helper, the installer
and systemd units, the frontend) and its default configuration.

Out of scope: vulnerabilities in the SIEM agents Habeny installs inside containers (report
them to the SIEM vendor), in LXC or the Linux kernel, and findings that need an attacker
who is already root on the host. Also out of scope: missing hardening that the
documentation tells you to turn on, and denial of service by flooding requests.

Please test only against your own installation. Don't access other people's data, and
don't disrupt systems you don't own.

## How Habeny is secured

A summary for reviewers and administrators. The README has the settings.

- **Privilege separation:** the web app runs as the unprivileged `habeny` user under
  systemd sandboxing. Container operations go through `habeny-helper`, a small root
  service on a Unix socket. It accepts only the `habeny` user (checked by peer
  credentials) and an allowlist of operations and LXC config keys.
- **Transport:** HTTPS by default: a self-signed certificate, or your own certificate
  with HSTS. There is also a reverse-proxy mode.
- **Accounts:**
  - scrypt password hashes
  - a password policy (12+ characters, common passwords refused)
  - a login rate limit
  - optional TOTP two-factor with one-time recovery codes
  - optional OpenID Connect single sign-on
  - roles: viewer, operator and admin
  - first-run setup protected by a one-time token
- **Sessions:** random tokens, and only their hashes are stored. They live in HttpOnly,
  SameSite=Strict cookies. Users can list and end their sessions; admins can sign
  anyone out.
- **Browser protections:** WebSocket origin checks. CORS is off unless you configure an
  explicit list of allowed origins.
- **Secrets at rest:** SIEM keys and enrollment tokens, and TOTP secrets, are encrypted
  (Fernet). They are never sent back to the browser.
- **Input handling:** container names, SIEM parameters and file paths are validated
  against allowlists. Values that reach a shell inside a container are quoted.
- **Process:**
  - CI runs the tests plus `pip-audit` and `npm audit` on every change and weekly.
  - Dependabot proposes dependency updates.
  - The scope for an independent review is in
    [docs/security-review-scope.md](docs/security-review-scope.md).
