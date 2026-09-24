# API guide

Everything the web interface does goes through Habeny's HTTP API, so scripts, CI pipelines
and other tools can do the same. This page explains how to call it. The list of endpoints,
with the role each needs and its parameters, is in [api-reference.md](api-reference.md).

## Contents

- [Base URL](#base-url)
- [Authentication](#authentication)
- [Requests and responses](#requests-and-responses)
- [Errors](#errors)
- [Common tasks](#common-tasks)
- [WebSockets](#websockets)
- [Monitoring endpoints](#monitoring-endpoints)
- [Compatibility](#compatibility)

## Base URL

```
https://<server>:9000/api
```

Every path in the reference is relative to it, e.g. `GET /agents` is
`https://habeny.example.com:9000/api/agents`. Behind a reverse proxy, use the proxy's
address. With Habeny's default self-signed certificate, give your client the certificate
(`curl --cacert`, taken from `/var/lib/lxc-siem-platform/tls/`) rather than turning off
verification.

The server also serves an interactive, generated description at `/api/docs` (Swagger UI)
and the OpenAPI 3.1 document at `/api/openapi.json`, which code generators accept. `/api/docs`
loads its page assets from a public CDN, so it needs internet access in the browser.

## Authentication

Use an **API token**:

```bash
export HABENY=https://habeny.example.com:9000/api
export HABENY_TOKEN=hby_…            # from Account → API tokens, shown once
curl -sS -H "Authorization: Bearer $HABENY_TOKEN" "$HABENY/agents/stats"
```

- Create tokens under **Account → API tokens**, or on the server with
  `sudo habeny token create <user> <name> [--role viewer|operator|admin] [--expires-days N]`.
- A token has at most its owner's role, and can be limited to a lower one. Use **viewer**
  tokens for monitoring and reporting, **operator** for automation that deploys or runs
  tests.
- Tokens can't change account settings (passwords, two-factor, other tokens); those need
  a signed-in browser session.
- Give tokens an expiry. The Account page shows when each was last used; revoke those you
  don't need. Every call made with a token is recorded in the audit trail under its name.
- A deleted or demoted user's tokens stop working or lose the removed rights immediately.

The browser interface uses a session cookie instead. Scripts shouldn't: cookies are tied
to a sign-in, can require two-factor, and expire.

**Roles**, as given for each endpoint in the reference:

| Role | Can call |
|---|---|
| viewer | every `GET` (read) endpoint |
| operator | also changes: deploy, start, stop, delete, simulations, log uploads, benchmarks, profiles, the console |
| admin | also users, teams, notifications, backups, other hosts, installing a license |

Team members only see their team's containers, simulations and reports: other containers
answer 404, as if they didn't exist.

## Requests and responses

- Send JSON bodies with `Content-Type: application/json`.
- Most endpoints answer with the same envelope:

  ```json
  {
    "success": true,
    "message": "Deployed 5/5 containers in 84.20s",
    "data": { "...": "the endpoint's result" },
    "error": null,
    "timestamp": "2026-09-24T19:30:00.123456Z"
  }
  ```

  **Check `success`, not only the HTTP status.** Some operations that partly fail (for
  example a deployment where 2 of 10 containers failed) answer HTTP 200 with
  `"success": false`, the details in `data` and a summary in `message`/`error`.
- Times are ISO 8601 in UTC.
- Lists that can be long take `limit` and `offset`, e.g.
  `GET /agents?limit=100&offset=200`, and filters such as `siem_type`, `status` and
  `agent_group`.
- Every response carries an **`X-Request-ID`** header. Quote it when you contact support:
  it finds the exact server log lines. You can send your own `X-Request-ID` (8 to 64
  letters, digits, `.`, `_`, `:` or `-`) to link your logs with Habeny's.

## Errors

Errors use HTTP status codes with a JSON body whose `detail` says what went wrong:

```json
{ "detail": "Container web-0001 not found" }
```

| Status | Meaning | What to do |
|---|---|---|
| 400 | The request can't be done as asked (e.g. a missing SIEM address) | Read `detail`, fix the request |
| 401 | No or invalid token or session | Check the token; it may be revoked or expired |
| 402 | The server's license doesn't allow new work (trial ended, expired, or over the container limit) | Ask your administrator; reads and managing existing containers still work |
| 403 | Your role or token doesn't allow this, or it would exceed a team or user container limit | Use a token with the right role, or ask an admin |
| 404 | Not found, or not visible to your team | |
| 409 | Conflicts with something that exists (e.g. a duplicate name) | |
| 422 | The body or parameters don't match the schema; `detail` lists each problem with its location | Fix the listed fields |
| 429 | Too many failed sign-ins from your address | Wait for `Retry-After` seconds |
| 500 | A server error; the body includes `request_id` | Retry once; if it persists, report it with the request ID |
| 503 | Shutting down or not ready (`/readyz`) | Retry after a short wait |

## Common tasks

The examples use `curl` and `jq`, with `HABENY` and `HABENY_TOKEN` set as above.

**List running Wazuh containers**

```bash
curl -sS -H "Authorization: Bearer $HABENY_TOKEN" \
  "$HABENY/agents?siem_type=wazuh&status=running&limit=500" | jq -r '.data.agents[].agent_name'
```

**Deploy containers and follow the progress**

`POST /agents/deploy` answers when the deployment has finished, which can take minutes.
To follow it while it runs, choose the `deployment_id` yourself and poll
`GET /agents/deploy/progress/{deployment_id}` from another process:

```bash
ID=ci-$(date +%s)
curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" -H "Content-Type: application/json" \
  "$HABENY/agents/deploy" -d "{
    \"deployment_id\": \"$ID\",
    \"count\": 5,
    \"manager_profile_id\": \"<profile id from GET /managers>\",
    \"agent_base_name\": \"ci-wazuh\",
    \"agent_group\": \"ci\"
  }" | jq '{success, message, failed: .data.failed_agents}' &

sleep 5
curl -sS -H "Authorization: Bearer $HABENY_TOKEN" "$HABENY/agents/deploy/progress/$ID" | jq '.data'
wait
```

Set your HTTP client's timeout generously (e.g. 30 minutes for large deployments). If the
connection drops, the deployment still finishes on the server; the progress endpoint and
`GET /agents?agent_group=ci` show the outcome.

**Run an attack simulation against a group, then stop it**

```bash
SIM=$(curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" -H "Content-Type: application/json" \
  "$HABENY/simulations/start" -d '{
    "profile_id": "auth_bruteforce",
    "agent_selector": {"agent_group": "ci"},
    "duration": 300,
    "intensity": "medium"
  }' | jq -r '.data.simulation_id')

curl -sS -H "Authorization: Bearer $HABENY_TOKEN" "$HABENY/simulations" | jq '.data'
curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" "$HABENY/simulations/$SIM/stop"
```

**Upload log lines into a container**

```bash
curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" -H "Content-Type: application/json" \
  "$HABENY/agents/ci-wazuh-0001/logs/upload" -d '{
    "content": "Sep 24 10:15:32 web sshd[1234]: Failed password for admin from 192.0.2.10 port 4242 ssh2\n",
    "destination_path": "/var/log/auth.log",
    "append": true
  }'
```

**Delete every container in a group**

```bash
NAMES=$(curl -sS -H "Authorization: Bearer $HABENY_TOKEN" "$HABENY/agents?agent_group=ci&limit=1000" \
  | jq -c '[.data.agents[].agent_name]')
curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" -H "Content-Type: application/json" \
  "$HABENY/agents/bulk/delete" -d "{\"operation\": \"delete\", \"container_names\": $NAMES}" | jq '.message'
```

**Export the audit trail** (CSV or JSON Lines, with the same filters as the Activity page):

```bash
curl -sS -H "Authorization: Bearer $HABENY_TOKEN" \
  "$HABENY/activity/export?format=jsonl&since=2026-09-01" > audit.jsonl
```

**Generate a report**

```bash
curl -sS -X POST -H "Authorization: Bearer $HABENY_TOKEN" -H "Content-Type: application/json" \
  "$HABENY/reports/generate" -d '{
    "start_time": "2026-09-24T00:00:00Z",
    "end_time": "2026-09-24T23:59:59Z",
    "format": "pdf"
  }' | jq '.data'
```

Check each endpoint's body in [api-reference.md](api-reference.md): the examples show the
usual fields, not every option.

## WebSockets

| Path | Role | What |
|---|---|---|
| `wss://<server>:9000/ws/metrics` | viewer | Live platform metrics, pushed every few seconds as JSON |
| `wss://<server>:9000/ws/console/<container>` | operator | An interactive root shell in a running container (terminal data in both directions) |

WebSockets authenticate with the session cookie, or with the token in the
`Authorization: Bearer` header of the upgrade request where your client supports it.

## Monitoring endpoints

| Endpoint | Sign-in | Use |
|---|---|---|
| `GET /api/healthz` | none | Liveness: 200 while the process answers |
| `GET /api/readyz` | none | Readiness: 200 when the database, LXC and the data disk are fine, else 503 |
| `GET /api/metrics` | viewer token | Prometheus metrics; see [admin-guide.md](admin-guide.md#monitoring-and-alerts) |

## Compatibility

Habeny follows [Semantic Versioning](https://semver.org/):

- **Minor and patch releases** (2.2 → 2.3) don't remove endpoints or fields and don't change
  what existing fields mean. They can add endpoints, optional request fields and response
  fields, so ignore response fields you don't know.
- **Major releases** (2.x → 3.0) can remove or change endpoints. Their release notes list
  every such change under "Upgrading". Where possible, an endpoint is marked deprecated in
  the release notes of a minor release before a major release removes it.

The release notes for each version are on the Releases page and in `CHANGELOG.md`.
