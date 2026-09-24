# API reference

Every endpoint of this version of Habeny, generated from the application by
`deploy/api_reference.py` (the tests check it's current). Read [api.md](api.md) first:
it explains authentication, the response format, errors and common tasks. Paths are
relative to `https://<server>:9000/api`. **Role** is the least role that may call it;
"none" needs no sign-in. The server's own `/docs` page has the full JSON schemas.

## Contents

- [Health and monitoring](#health-and-monitoring)
- [Sign-in and setup](#sign-in-and-setup)
- [Your account, users and API tokens](#your-account-users-and-api-tokens)
- [Teams](#teams)
- [License](#license)
- [Containers](#containers)
- [Groups](#groups)
- [Manager profiles](#manager-profiles)
- [Configuration templates](#configuration-templates)
- [Syslog configurations](#syslog-configurations)
- [Simulations](#simulations)
- [Benchmarks](#benchmarks)
- [SIEM statistics](#siem-statistics)
- [Reports](#reports)
- [Activity (audit trail)](#activity-audit-trail)
- [Notifications](#notifications)
- [Backups](#backups)
- [Other hosts](#other-hosts)
- [System](#system)
- [Live data (WebSocket)](#live-data-websocket)

## Health and monitoring

### `GET /healthz`

The process is up and answering.

- **Role:** none

### `GET /readyz`

Ready for work: database answers, LXC is reachable, data disk isn't nearly full, not stopping.

- **Role:** none

### `GET /metrics`

Prometheus metrics (see app/services/telemetry.py for the scrape configuration).

- **Role:** viewer

### `GET /system/alerts`

List Alerts

- **Role:** viewer

### `GET /system/health`

Comprehensive health check endpoint

- **Role:** viewer

### `GET /metrics/benchmarks`

Get deployment and simulation performance benchmarks with percentiles

- **Role:** viewer
- **Query:** `since`

### `GET /metrics/history`

Get raw metrics history for charting

- **Role:** viewer
- **Query:** `metric_type` (required), `metric_name`, `since`, `limit`

### `GET /metrics/system`

Get current system resource metrics

- **Role:** viewer

## Sign-in and setup

### `GET /auth/status`

Whether first-run setup is needed and who (if anyone) is signed in

- **Role:** none

### `POST /auth/setup`

Create the first (admin) account. Only allowed while no account exists, and only

- **Role:** none
- **Body (JSON):**
  - `setup_token` (required): string
  - `username` (required): string
  - `password` (required): string

### `POST /auth/login`

Login

- **Role:** none
- **Body (JSON):**
  - `username` (required): string
  - `password` (required): string

### `POST /auth/login/2fa`

Login Second Factor

- **Role:** none
- **Body (JSON):**
  - `mfa_token` (required): string
  - `code` (required): string

### `POST /auth/logout`

Logout

- **Role:** none

### `GET /auth/oidc/login`

Send the browser to the identity provider.

- **Role:** none

### `GET /auth/oidc/callback`

The identity provider sends the browser back here with an authorization code.

- **Role:** none
- **Query:** `state`, `code`, `error`, `error_description`

## Your account, users and API tokens

### `POST /users/me/password`

Change your own password. Signs out your other sessions.

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `current_password` (required): string
  - `new_password` (required): string

### `GET /users/me/2fa`

My Two Factor

- **Role:** signed in (browser session)

### `POST /users/me/2fa/setup`

Start enrolling an authenticator app: returns a new secret (shown as a QR code).

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `current_password` (required): string

### `POST /users/me/2fa/enable`

Confirm enrolment with a code from the app. Returns one-time recovery codes (shown once).

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `code` (required): string

### `POST /users/me/2fa/recovery-codes`

Replace your recovery codes (the old ones stop working).

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `current_password` (required): string

### `POST /users/me/2fa/disable`

Disable Two Factor

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `current_password` (required): string
  - `code` (required): string

### `GET /users/me/sessions`

Your active sessions (browsers/devices signed in to your account).

- **Role:** signed in (browser session)

### `DELETE /users/me/sessions/{session_id}`

Sign out one of your sessions.

- **Role:** signed in (browser session)

### `POST /users/me/sessions/revoke-others`

Sign out everywhere except this browser.

- **Role:** signed in (browser session)

### `GET /users/me/tokens`

My Tokens

- **Role:** signed in (browser session)

### `POST /users/me/tokens`

Create an API token for scripts and CI: send it as `Authorization: Bearer <token>`.

- **Role:** signed in (browser session)
- **Body (JSON):**
  - `name` (required): string
  - `role`: `viewer` \| `operator` \| `admin` (optional)
  - `expires_in_days`: integer (optional), default `90`

### `DELETE /users/me/tokens/{token_id}`

Revoke My Token

- **Role:** signed in (browser session)

### `GET /users/tokens`

Every user's API tokens (admins), e.g. to find unused or never-expiring ones.

- **Role:** admin

### `DELETE /users/tokens/{token_id}`

Revoke Token

- **Role:** admin

### `GET /users`

Get Users

- **Role:** admin

### `POST /users`

Add User

- **Role:** admin
- **Body (JSON):**
  - `username` (required): string
  - `password` (required): string
  - `role`: `viewer` \| `operator` \| `admin`, default `viewer`

### `PATCH /users/{user_id}`

Update User

- **Role:** admin
- **Body (JSON):**
  - `role` (required): `viewer` \| `operator` \| `admin`

### `POST /users/{user_id}/password`

Set a new password for another user and sign them out everywhere.

- **Role:** admin
- **Body (JSON):**
  - `new_password` (required): string

### `GET /users/{user_id}/sessions`

User Sessions

- **Role:** admin

### `POST /users/{user_id}/sessions/revoke`

Sign a user out everywhere (e.g. a lost laptop).

- **Role:** admin

### `DELETE /users/{user_id}/2fa`

For a user who lost their authenticator and recovery codes: turn 2FA off so they

- **Role:** admin

### `DELETE /users/{user_id}`

Remove User

- **Role:** admin

### `PUT /users/{user_id}/team`

Set User Team

- **Role:** admin
- **Body (JSON):**
  - `team_id`: integer (optional)
  - `max_containers`: integer (optional)

## Teams

### `GET /teams`

List Teams

- **Role:** admin

### `POST /teams`

Create Team

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `description`: string (optional)
  - `max_containers`: integer (optional)

### `PUT /teams/{team_id}`

Update Team

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `description`: string (optional)
  - `max_containers`: integer (optional)

### `DELETE /teams/{team_id}`

Its members and containers go back to having no team.

- **Role:** admin

### `POST /teams/assign`

Move existing containers to a team (or to no team).

- **Role:** admin
- **Body (JSON):**
  - `team_id`: integer (optional)
  - `containers` (required): list of string

## License

### `GET /license`

Get License

- **Role:** signed in

### `POST /license`

Install License

- **Role:** admin
- **Body (JSON):**
  - `license` (required): string

## Containers

### `GET /agents/deploy/progress/{deployment_id}`

Live progress (per-container steps and an activity feed) of a deployment

- **Role:** viewer

### `POST /agents/deploy`

Deploy multiple containers with SIEM agents

- **Role:** operator
- **Body (JSON):**
  - `count` (required): integer
  - `manager_profile_id`: string (optional)
  - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic`, default `wazuh`
  - `siem_ip`: string (optional)
  - `siem_version`: string (optional), default `4.14.2`
  - `os_type`: `ubuntu_22_04` \| `ubuntu_20_04` \| `debian_11` \| `debian_10` \| `centos_8`, default `ubuntu_22_04`
  - `agent_group`: string, default `default`
  - `agent_base_name`: string, default `container`
  - `memory_limit`: string (optional), default `512MB`
  - `cpu_shares`: integer (optional), default `1024`
  - `config_template_id`: string (optional)
  - `autostart`: boolean (optional), default `True`
  - `parallel_mode`: `sequential` \| `threading` \| `multiprocessing`, default `multiprocessing`
  - `auto_create_group`: boolean (optional), default `True`
  - `siem_auth_key`: string (optional)
  - `deployment_id`: string (optional)

### `GET /agents`

List the containers you can see (all for admins; your team's otherwise), filtered and paged

- **Role:** viewer
- **Query:** `siem_type`, `status`, `agent_group`, `limit`, `offset`

### `GET /agents/stats`

Container totals (for your team's containers unless you're an admin)

- **Role:** viewer

### `GET /agents/{agent_id}`

Get detailed information about a specific container

- **Role:** viewer

### `DELETE /agents/{agent_id}`

Delete a container and optionally unregister from SIEM

- **Role:** operator

### `POST /agents/bulk/{operation}`

Perform bulk operations on multiple containers

- **Role:** operator
- **Body (JSON):**
  - `container_names` (required): list of string
  - `operation` (required): string
  - `force`: boolean, default `False`
  - `parallel`: boolean, default `True`
  - `max_workers`: integer (optional)

### `POST /agents/{agent_id}/start`

Start a container

- **Role:** operator

### `POST /agents/{agent_id}/stop`

Stop a container

- **Role:** operator

### `POST /agents/{agent_id}/enable-syslog`

Enable syslog on a UTMstack container (port 7014) and create a syslog config profile

- **Role:** operator
- **Query:** `protocol`

### `POST /agents/{agent_id}/disable-syslog`

Disable syslog on a UTMstack container

- **Role:** operator
- **Query:** `protocol`

### `POST /agents/{agent_id}/logs/schedule`

Schedule periodic log uploads to a container.

- **Role:** operator
- **Body (JSON):**
  - `content` (required): string
  - `destination_path` (required): string
  - `log_type`: `auth` \| `web` \| `application` \| `system` \| `security` \| `custom`, default `custom`
  - `append`: boolean, default `True`
  - `interval_seconds`: integer, default `120`
  - `duration_seconds`: integer (optional)
  - `indefinite`: boolean, default `False`

### `POST /agents/logs/schedules/{schedule_id}/stop`

Stop a scheduled log upload.

- **Role:** operator

### `GET /agents/logs/schedules`

List the log upload schedules for containers you can see.

- **Role:** viewer

### `POST /agents/{agent_id}/logs/upload`

Upload log content to a container

- **Role:** operator
- **Body (JSON):**
  - `content` (required): string
  - `destination_path` (required): string
  - `log_type`: `auth` \| `web` \| `application` \| `system` \| `security` \| `custom`, default `custom`
  - `append`: boolean, default `False`

## Groups

### `GET /groups`

List all container groups with counts (of the containers you can see).

- **Role:** viewer

### `POST /groups`

Create a new container group.

- **Role:** operator
- **Body (JSON):**
  - `name` (required): string
  - `description`: string (optional)

### `POST /groups/{group_name}/rename`

Rename a container group.

- **Role:** operator
- **Body (JSON):**
  - `new_name` (required): string
  - `description`: string (optional)

### `DELETE /groups/{group_name}`

Delete a container group and unassign containers.

- **Role:** operator

### `POST /groups/{group_name}/assign`

Assign containers to a group.

- **Role:** operator
- **Body (JSON):**
  - `agent_ids` (required): list of string

### `POST /groups/{group_name}/remove`

Remove containers from a group.

- **Role:** operator
- **Body (JSON):**
  - `agent_ids` (required): list of string

### `POST /groups/{group_name}/bulk/{operation}`

Perform bulk operations on all containers in a group.

- **Role:** operator

### `POST /groups/{group_name}/logs/upload`

Upload log content to all containers in a group.

- **Role:** operator
- **Body (JSON):**
  - `content` (required): string
  - `destination_path` (required): string
  - `log_type`: `auth` \| `web` \| `application` \| `system` \| `security` \| `custom`, default `custom`
  - `append`: boolean, default `False`

### `POST /groups/{group_name}/logs/schedule`

Schedule periodic log uploads to all containers in a group.

- **Role:** operator
- **Body (JSON):**
  - `content` (required): string
  - `destination_path` (required): string
  - `log_type`: `auth` \| `web` \| `application` \| `system` \| `security` \| `custom`, default `custom`
  - `append`: boolean, default `True`
  - `interval_seconds`: integer, default `120`
  - `duration_seconds`: integer (optional)
  - `indefinite`: boolean, default `False`

## Manager profiles

### `GET /managers`

List all manager profiles

- **Role:** viewer

### `GET /managers/{manager_id}`

Get a single manager profile

- **Role:** viewer

### `POST /managers`

Create a manager profile

- **Role:** operator
- **Body (JSON):**
  - `name` (required): string
  - `description`: string (optional)
  - `siem_type` (required): `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic`
  - `siem_ip`: string (optional)
  - `siem_version`: string (optional)
  - `siem_auth_key`: string (optional)
  - `os_type`: `ubuntu_22_04` \| `ubuntu_20_04` \| `debian_11` \| `debian_10` \| `centos_8`, default `ubuntu_22_04`
  - `agent_group`: string, default `default`
  - `memory_limit`: string (optional), default `512MB`
  - `cpu_shares`: integer (optional), default `1024`
  - `config_template_id`: string (optional)

### `PUT /managers/{manager_id}`

Update a manager profile

- **Role:** operator
- **Body (JSON):**
  - `name`: string (optional)
  - `description`: string (optional)
  - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic` (optional)
  - `siem_ip`: string (optional)
  - `siem_version`: string (optional)
  - `siem_auth_key`: string (optional)
  - `os_type`: `ubuntu_22_04` \| `ubuntu_20_04` \| `debian_11` \| `debian_10` \| `centos_8` (optional)
  - `agent_group`: string (optional)
  - `memory_limit`: string (optional)
  - `cpu_shares`: integer (optional)
  - `config_template_id`: string (optional)

### `DELETE /managers/{manager_id}`

Delete a manager profile

- **Role:** operator

## Configuration templates

### `GET /configs`

List all configuration templates

- **Role:** viewer

### `POST /configs/import`

Import a configuration template

- **Role:** operator
- **Body (JSON):**
  - `name` (required): string
  - `siem_type` (required): `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic`
  - `content` (required): string
  - `description`: string (optional)
  - `version`: string (optional)
  - `tags`: list of string

### `GET /configs/export/{template_id}`

Export a configuration template

- **Role:** viewer

## Syslog configurations

### `GET /syslog-configs`

List all syslog config profiles

- **Role:** viewer

### `POST /syslog-configs`

Create a syslog config profile

- **Role:** operator
- **Body (JSON):**
  - `name` (required): string
  - `description`: string (optional)
  - `manager_profile_id`: string (optional)
  - `target_ip` (required): string
  - `target_port`: integer, default `514`
  - `protocol`: `udp` \| `tcp`, default `tcp`
  - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic` (optional)

### `GET /syslog-configs/{config_id}`

Get a syslog config profile

- **Role:** viewer

### `PUT /syslog-configs/{config_id}`

Update a syslog config profile

- **Role:** operator
- **Body (JSON):**
  - `name`: string (optional)
  - `description`: string (optional)
  - `manager_profile_id`: string (optional)
  - `target_ip`: string (optional)
  - `target_port`: integer (optional)
  - `protocol`: `udp` \| `tcp` (optional)
  - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic` (optional)

### `DELETE /syslog-configs/{config_id}`

Delete a syslog config profile

- **Role:** operator

### `POST /syslog-configs/test-connectivity`

Test TCP/UDP connectivity to a syslog target

- **Role:** operator
- **Query:** `target_ip` (required), `target_port`, `protocol`

## Simulations

### `GET /simulations`

List simulations (running and completed): all for admins, your team's otherwise

- **Role:** viewer

### `POST /simulations/load`

Load custom EPS simulations using JSON log templates.

- **Role:** operator
- **Body (JSON):**
  - `agent_selector` (required): AgentSelector
    - `agent_ids`: list of string (optional)
    - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic` (optional)
    - `agent_group`: string (optional)
    - `tags`: list of string (optional)
    - `count`: integer (optional)
    - `status`: `running` \| `stopped` \| `error` \| `starting` \| `stopping` (optional)
  - `file_path`: string, default `/var/log/custom-eps.json`
  - `message`: string, default `Custom EPS log event`
  - `src_ip`: string, default `192.168.1.100`
  - `dest_ip`: string, default `10.0.0.1`
  - `duration`: integer, default `300`
  - `eps`: integer, default `100`
  - `seq_start`: integer, default `1`
  - `start_time`: string (optional)
  - `extra_fields`: object

### `POST /simulations/syslog/start`

Start a syslog simulation to a target IP/port.

- **Role:** operator
- **Body (JSON):**
  - `target_ip` (required): string
  - `target_port`: integer, default `514`
  - `protocol`: `udp` \| `tcp`, default `tcp`
  - `eps`: integer, default `100`
  - `duration`: integer, default `300`
  - `device_count`: integer, default `4`
  - `device_type`: `router` \| `switch` \| `firewall` \| `ids` \| `mixed`, default `mixed`
  - `device_name_prefix`: string, default `device`
  - `facility`: integer, default `1`

### `POST /simulations/start`

Start an attack simulation on selected containers

- **Role:** operator
- **Body (JSON):**
  - `profile_id` (required): `auth_bruteforce` \| `web_attacks` \| `malware_beacon` \| `lateral_movement` \| `data_exfiltration` \| `privilege_escalation` \| `port_scan` \| `sql_injection` \| `xss_attack` \| `ddos_attack`
  - `agent_selector` (required): AgentSelector
    - `agent_ids`: list of string (optional)
    - `siem_type`: `none` \| `wazuh` \| `ossec` \| `utmstack` \| `elastic` (optional)
    - `agent_group`: string (optional)
    - `tags`: list of string (optional)
    - `count`: integer (optional)
    - `status`: `running` \| `stopped` \| `error` \| `starting` \| `stopping` (optional)
  - `duration`: integer, default `300`
  - `eps_target`: integer, default `100`
  - `intensity`: string (optional), default `medium`
  - `burst_mode`: boolean (optional), default `False`
  - `custom_parameters`: object (optional)

### `POST /simulations/{simulation_id}/stop`

Stop a running simulation

- **Role:** operator

## Benchmarks

### `GET /benchmarks/scenarios`

List available benchmark scenarios

- **Role:** viewer

### `POST /benchmarks/start`

Start a benchmark execution

- **Role:** operator
- **Body (JSON):**
  - `scenario_id`: string, default `linear_scale`
  - `name`: string (optional)
  - `siem_type`: string (optional), default `none`
  - `siem_ip`: string (optional)
  - `siem_version`: string (optional)
  - `siem_auth_key`: string (optional)
  - `base_name`: string (optional)
  - `memory_limit`: string (optional), default `256MB`
  - `os_type`: string (optional), default `ubuntu_22_04`
  - `agent_group`: string (optional), default `benchmark`
  - `metric_interval`: integer (optional)
  - `failure_threshold`: number (optional)
  - `manager_profile_id`: string (optional)

### `POST /benchmarks/{benchmark_id}/stop`

Stop a running benchmark

- **Role:** operator

### `POST /benchmarks/cleanup`

Mark all stale 'running' benchmarks as aborted

- **Role:** operator

### `GET /benchmarks`

List all benchmarks

- **Role:** viewer

### `GET /benchmarks/{benchmark_id}`

Get detailed benchmark results

- **Role:** viewer

### `GET /benchmarks/{benchmark_id}/metrics`

Get time-series metrics for a benchmark

- **Role:** viewer
- **Query:** `category`, `limit`

### `GET /benchmarks/{benchmark_id}/bottlenecks`

Get detected bottlenecks for a benchmark

- **Role:** viewer

### `POST /benchmarks/compare`

Compare multiple benchmarks side-by-side

- **Role:** operator
- **Body (JSON):**
  - `benchmark_ids` (required): list of string

## SIEM statistics

### `GET /siem/{siem_type}/stats`

Get statistics for a specific SIEM type

- **Role:** viewer

## Reports

### `POST /reports/generate`

Generate a performance/benchmark report (over your team's containers unless you're an admin)

- **Role:** operator
- **Body (JSON):**
  - `start_time` (required): string
  - `end_time` (required): string
  - `siem_ids`: list of string (optional)
  - `scenario_ids`: list of string (optional)
  - `metrics`: list of string
  - `include_findings`: boolean, default `True`
  - `format`: string, default `json`

### `GET /reports/{report_id}`

Retrieve a generated report

- **Role:** viewer

### `GET /reports/{report_id}/download`

Download report in the requested format (json, csv, pdf).

- **Role:** viewer
- **Query:** `format`

## Activity (audit trail)

### `GET /activity/logs`

Newest-first page of the audit trail, filtered by action, user, status, dates or text.

- **Role:** viewer
- **Query:** `limit`, `offset`, `action`, `user`, `status`, `since`, `until`, `q`

### `GET /activity/facets`

The actions and users in the trail, for filter menus.

- **Role:** viewer

### `GET /activity/export`

Download matching entries (oldest first) as CSV or JSON Lines, with their hashes.

- **Role:** viewer
- **Query:** `format`, `action`, `user`, `status`, `since`, `until`, `q`

### `GET /activity/verify`

Recompute the hash chain: shows whether any entry was changed, removed or reordered.

- **Role:** admin

## Notifications

### `GET /notifications/channels`

Get Channels

- **Role:** admin

### `POST /notifications/channels`

Add Channel

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `type`: string, default `webhook`
  - `config`: object
  - `events`: list of string
  - `only_problems`: boolean, default `False`
  - `enabled`: boolean, default `True`

### `PUT /notifications/channels/{channel_id}`

Edit Channel

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `type`: string, default `webhook`
  - `config`: object
  - `events`: list of string
  - `only_problems`: boolean, default `False`
  - `enabled`: boolean, default `True`

### `DELETE /notifications/channels/{channel_id}`

Remove Channel

- **Role:** admin

### `POST /notifications/channels/{channel_id}/test`

Send a test message now and report whether it went through.

- **Role:** admin

## Backups

### `GET /system/backups`

List Backups

- **Role:** admin

### `POST /system/backups`

Create Backup

- **Role:** admin

### `GET /system/backups/{name}`

Download Backup

- **Role:** admin

## Other hosts

### `GET /hosts`

The hosts you can use (all for admins).

- **Role:** viewer

### `GET /hosts/overview`

Every usable host's status, version, containers and alerts, fetched in parallel.

- **Role:** viewer

### `POST /hosts`

Add Host

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `url`: string, default ``
  - `token`: string, default ``
  - `fingerprint`: string (optional)
  - `team_id`: integer (optional)

### `PUT /hosts/{host_id}`

Edit Host

- **Role:** admin
- **Body (JSON):**
  - `name` (required): string
  - `url`: string, default ``
  - `token`: string, default ``
  - `fingerprint`: string (optional)
  - `team_id`: integer (optional)

### `DELETE /hosts/{host_id}`

Remove Host

- **Role:** admin

### `WS /hosts/{host_id}/ws/{path:path}`

Relay a WebSocket (live metrics, container console) to the host.

- **Role:** viewer

## System

### `GET /`

Root endpoint with comprehensive API information

- **Role:** viewer

### `GET /system/info`

Get comprehensive system and LXC information

- **Role:** viewer

## Live data (WebSocket)

### `WS /ws/metrics`

Push live platform metrics to connected React dashboards.

- **Role:** viewer

### `WS /ws/console/{container_name}`

WebSocket console session into a running container.

- **Role:** operator
