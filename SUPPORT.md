# Getting support

## Before you contact us

1. Look in the [troubleshooting guide](docs/troubleshooting.md), and in the
   [administrator](docs/admin-guide.md) and [user](docs/user-guide.md) guides.
2. Check you're on a supported version (below): `sudo habeny version`.

## How to reach us

| For | Where |
|---|---|
| Problems, questions, how-to | Email **[mustaphakasim001@gmail.com](mailto:mustaphakasim001@gmail.com)** |
| Bugs and feature requests (if you can see this repository) | [GitHub issues](https://github.com/Cyber-MKO/Habeny/issues/new/choose) |
| Security vulnerabilities | **Never in a public issue.** See [SECURITY.md](SECURITY.md) |
| Licenses, renewals, moving a license to a new server | Email, with your license number and server ID (`sudo habeny license request`) |

Start the email subject with the severity, e.g. `[P1] Deployments fail on all hosts`.

## What to send

- **What happened and what you expected**, and what you were doing: the page, or the API
  call and its body.
- **When** it happened (with time zone), and the **request ID** from the error message if
  there was one.
- **A support bundle.** It gives us versions, settings (with secrets hidden), service,
  database and license state, and the end of the server log:

  ```bash
  sudo habeny support-bundle        # prints the file's path, e.g. /tmp/habeny-support-….tar.gz
  ```

  It never contains passwords, keys, your license file, the database or uploaded logs. The
  log excerpt can include user names, IP addresses and container names, so look through it
  before sending it, and **send it by email, not in a public issue**.
- For deployment and agent problems: the SIEM type and version, and the output from
  Containers → Details for one failing container.

## Severity levels

| Level | Meaning | Examples |
|---|---|---|
| **P1 Critical** | Habeny is down or unusable for everyone, or data is being lost, and there's no workaround | The service won't start after an upgrade; every deployment fails; backups corrupt |
| **P2 High** | A major feature doesn't work, or works only with a painful workaround | One SIEM type can't be deployed; simulations don't start; SSO sign-in fails |
| **P3 Normal** | A problem with a reasonable workaround, or a question | A page shows wrong numbers; how to configure something |
| **P4 Low** | Cosmetic issues, documentation, feature requests | Typos, layout on small screens, a new report format |

We may change the level after looking at the issue, and we'll tell you if we do.

## Support plans

Two plans are offered; their response times, hours and exclusions are in the
[support terms](docs/legal/SUPPORT-TERMS.md). Your order says which plan you have.

| | Standard | Premium |
|---|---|---|
| Channel | Email | Email, plus a phone or video call for P1 |
| Hours | Business hours | Extended hours; P1 around the clock |
| First response, P1 | 1 business day | 4 hours |
| First response, P2 | 2 business days | 1 business day |
| First response, P3/P4 | 5 business days | 2 business days |

## Supported versions

We support the **current minor release** (e.g. 2.2.x) and the **previous one** (2.1.x). Fixes
are released for the current minor version, and security fixes for both. Older versions
get help to upgrade. Release notes for every version are on the
[Releases page](https://github.com/Cyber-MKO/Habeny/releases) and in
[CHANGELOG.md](CHANGELOG.md); read the "Upgrading" notes before you upgrade.
