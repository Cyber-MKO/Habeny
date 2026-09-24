# Data, privacy and retention

What Habeny stores, where, for how long, and what it sends elsewhere. Use it to answer
customers' questions, or as the basis for a record of processing.

In short:
- Habeny is self-hosted. Everything it stores is on the customer's server, under
  `HABENY_DATA_DIR` (default `/var/lib/lxc-siem-platform`), in the containers it creates,
  and in the backup directory.
- **It sends nothing to Habeny Platform:** no telemetry, usage statistics, crash reports
  or license check-ins. Licenses are checked offline. The outbound connections it makes
  are listed below, and each is to a destination the customer configures or a vendor's
  download server.
- Uploaded log content is written into the target container. It's kept in Habeny's own
  database only for **scheduled** uploads, and only until that record passes
  `HABENY_HISTORY_RETENTION_DAYS`.

## What is stored

| Data | Where | Kept | How to delete |
|---|---|---|---|
| **Accounts**: username, password hash (scrypt), role, team, 2FA secret and hashed recovery codes, SSO subject ID, created and last sign-in time | database `platform.db`, table `users` | until the account is deleted | Account → Users → Delete |
| **Sessions**: hashed token, client IP, browser user agent, times | `sessions` | until sign-out or expiry (`HABENY_SESSION_TTL_HOURS`), then pruned hourly | sign out; Account → Sessions |
| **API tokens**: name, hash, role, last use time | `api_tokens` | until revoked; expired ones are pruned | Account → API tokens, `habeny token revoke` |
| **Audit trail**: time, action, result, username, token name, client IP, request ID and action details (e.g. container names, settings changed). Habeny doesn't record passwords, token values, keys or log content in it | `audit_log` | `HABENY_HISTORY_RETENTION_DAYS` (default 365) | lower the setting; `habeny prune` |
| **Uploaded logs, one-off** (Log Upload) | written to the chosen path **inside the container**; not stored by Habeny | until the container is deleted or the file is removed | delete the container |
| **Uploaded logs, scheduled** | the schedule record (`records` table) holds the content so it can re-upload it; also written in the container | the record: `HABENY_HISTORY_RETENTION_DAYS` after the schedule ends | stop the schedule; lower the setting; delete the container |
| **Simulations**: settings, custom log templates, target addresses, counts and results | `records` | `HABENY_HISTORY_RETENTION_DAYS` after they finish | lower the setting; `habeny prune` |
| **Generated attack and syslog traffic** | sent to the SIEM managers and syslog targets you choose; written inside containers | as those systems keep it | on those systems |
| **Deployments, benchmarks**: settings, per-container results, timings (SIEM auth keys are removed from stored benchmark settings) | `records`, `benchmarks`, `benchmark_*` | `HABENY_HISTORY_RETENTION_DAYS` after they finish | lower the setting |
| **Metrics**: CPU, memory, disk, API latency samples | `metrics` | `HABENY_METRICS_RETENTION_DAYS` (default 30) | lower the setting |
| **Reports** (PDF/CSV/JSON) | `DATA_DIR/reports` | `HABENY_REPORT_RETENTION_DAYS` (default 0: kept) | Reports page; set the setting |
| **SIEM manager profiles**: addresses, versions, auth keys (encrypted with `secret.key`) | `managers` | until deleted | Managers page |
| **Configuration templates, syslog configs, groups** | database and `DATA_DIR/configs` | until deleted | their pages |
| **Notification channels**: webhook/Slack URLs, email addresses (secrets encrypted) | `notification_channels` | until deleted | Notifications page |
| **Other hosts**: address, pinned certificate fingerprint, API token (encrypted) | `hosts` | until removed | Hosts page |
| **Containers**: agent configuration, SIEM enrollment keys, uploaded logs, anything the agents collect | `/var/lib/lxc/<name>` | until the container is deleted | Containers page, Bulk Ops |
| **Agent package cache** | `DATA_DIR/agent-cache` | kept to speed up deployments; not in backups | delete the directory |
| **Application log**: request lines with username, client IP, request ID; errors | stdout (journald), and `HABENY_LOG_FILE` if set | journald's settings; `HABENY_LOG_MAX_MB` × `HABENY_LOG_BACKUPS` | `journalctl --vacuum-time`; delete files |
| **Backups**: all of the above except containers and the package cache, plus `secret.key` and `habeny.conf` | `HABENY_BACKUP_DIR` (default `DATA_DIR/backups`) | the newest `HABENY_BACKUP_KEEP` (default 14) | delete backup files |
| **License**: license file, server ID | `DATA_DIR/license.key` | until replaced | delete the file |

Deleting something removes it from the live database right away. It stays in existing
backups until they rotate out, so with the defaults (daily backups, 14 kept) it's gone
from this server about two weeks later, and from any copies you made of the backups when
you delete them.

The audit trail is hash-chained. Pruning old entries keeps the chain verifiable, because
the oldest kept entry becomes the new anchor. Deleting individual entries breaks the
chain, and `habeny audit verify` then reports it.

## Outbound connections

Habeny connects only to:

| Destination | When | Configured by |
|---|---|---|
| Agent download servers: packages.wazuh.com, artifacts.elastic.co, updates.atomicorp.com, github.com (OSSIM), and the OS image and package mirrors the containers use | deploying agents | the SIEM type chosen (see [legal/siem-vendors.md](legal/siem-vendors.md)) |
| SIEM managers, the UTMStack server, Elastic Fleet | the agents enroll and send events; simulations send traffic | manager profiles, deploy and simulation forms |
| Syslog targets | syslog simulations | the simulation form |
| OpenID Connect provider | SSO sign-in | `HABENY_OIDC_*` |
| Slack, webhooks, mail server | notifications | Notifications page, `HABENY_SMTP_*` |
| Other Habeny servers | the Hosts feature | Hosts page |

Habeny sends no data to Habeny Platform or any other third party on its own. Firewalls
can block everything not on this list.

## Retention settings

| Setting | Default | Covers |
|---|---|---|
| `HABENY_HISTORY_RETENTION_DAYS` | 365 | audit trail, deployment results, finished simulations, benchmarks and log schedules |
| `HABENY_METRICS_RETENTION_DAYS` | 30 | system and API-latency samples |
| `HABENY_REPORT_RETENTION_DAYS` | 0 (keep) | generated report files |
| `HABENY_SESSION_TTL_HOURS` | 168 | how long a sign-in lasts |
| `HABENY_BACKUP_KEEP` | 14 | full backups kept |

Pruning runs hourly and on demand with `habeny prune` (`--dry-run` shows the counts
first). 0 means "keep forever" for the first two settings.

## If telemetry or crash reporting is ever added

Today there is none. If it's added:
- make it opt-in and off by default, with a setting (e.g. `HABENY_TELEMETRY`) and a
  toggle for admins that shows exactly what would be sent;
- never include log content, container names, IP addresses, usernames, SIEM addresses or
  keys, and strip them from crash reports (stack traces can contain request values);
- update this page and publish a privacy policy first
  ([legal/PRIVACY-POLICY.md](legal/PRIVACY-POLICY.md) is a draft for that case), and add
  the destination to the outbound-connections table above.
