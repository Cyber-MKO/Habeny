#!/usr/bin/env bash
# End-to-end check of an installed Habeny against real LXC (run as root after
# deploy/install.sh; used by .github/workflows/integration.yml):
# first admin → deploy a real container → start/stop it → attack simulations → full backup
# and verify → delete it.
set -euo pipefail

BASE="${HABENY_URL:-https://127.0.0.1:9000}"
DATA_DIR="${HABENY_DATA_DIR:-/var/lib/lxc-siem-platform}"
NAME="itest"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

step() { echo; echo "==> $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
# api METHOD PATH [JSON]: prints the response body; fails on HTTP errors
api() {
    local args=(-sS -k --fail-with-body -b "$JAR" -c "$JAR" -X "$1" -H "Content-Type: application/json" --max-time 900)
    [ $# -ge 3 ] && args+=(-d "$3")
    curl "${args[@]}" "$BASE$2"
}
field() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

step "Waiting for Habeny"
for _ in $(seq 60); do
    curl -sk --max-time 2 "$BASE/system/health" >/dev/null && break
    sleep 1
done
api GET /auth/status | field 'd["data"]["setup_required"]' | grep -qx True || fail "expected a fresh install"

step "Creating the first admin with the setup token"
TOKEN="$(cat "$DATA_DIR/setup-token")"
api POST /auth/setup "{\"username\":\"admin\",\"password\":\"integration-test-passphrase\",\"setup_token\":\"$TOKEN\"}" >/dev/null
[ ! -e "$DATA_DIR/setup-token" ] || fail "the setup token should be removed once used"
api GET /auth/status | field 'd["data"]["user"]["username"]' | grep -qx admin || fail "not signed in"

step "Health probes (no sign-in) and an API token for Prometheus"
curl -sSk --fail "$BASE/healthz" | grep -q '"status":"ok"' || fail "/healthz"
curl -sSk --fail "$BASE/readyz" | grep -q '"status":"ready"' || fail "/readyz not ready"
PROM_TOKEN="$(api POST /users/me/tokens '{"name":"prometheus","role":"viewer"}' | field 'd["data"]["token"]')"
[ "$(curl -sk -o /dev/null -w '%{http_code}' "$BASE/metrics")" = 401 ] || fail "/metrics without a token"

step "Deploying one container (downloads the Ubuntu 22.04 image)"
RESULT="$(api POST /agents/deploy "{\"count\":1,\"siem_type\":\"none\",\"agent_base_name\":\"$NAME\",\"parallel_mode\":\"sequential\",\"deployment_id\":\"itest-1\"}")"
echo "$RESULT" | field 'd["message"]'
echo "$RESULT" | field 'd["success"]' | grep -qx True || { echo "$RESULT" >&2; fail "deployment failed"; }
CONTAINER="$(echo "$RESULT" | field 'd["data"]["deployed_agents"][0]["agent_name"]')"
lxc-ls --running | tr -s ' \n' '\n' | grep -qx "$CONTAINER" || fail "$CONTAINER isn't running according to lxc-ls"
lxc-attach -n "$CONTAINER" -- cat /etc/os-release | grep -q jammy || fail "not an Ubuntu 22.04 container"
api GET /agents/deploy/progress/itest-1 | field 'd["data"]["status"]' | grep -qx completed || fail "progress not completed"

step "Metrics see the container"
sleep 3  # past the container-state cache
curl -sSk --fail -H "Authorization: Bearer $PROM_TOKEN" "$BASE/metrics" > /tmp/habeny-metrics.txt
grep -q '^habeny_containers{state="running"} 1' /tmp/habeny-metrics.txt || { cat /tmp/habeny-metrics.txt >&2; fail "metrics"; }
grep -q '^habeny_deployments_total{result="completed"} 1' /tmp/habeny-metrics.txt || fail "deployment counter"

step "Container details, stop and start"
api GET "/agents/$CONTAINER" | field 'd["data"]["lifecycle_status"]'
api POST "/agents/$CONTAINER/stop" >/dev/null
lxc-info -n "$CONTAINER" -s | grep -q STOPPED || fail "$CONTAINER didn't stop"
api POST "/agents/$CONTAINER/start" >/dev/null
lxc-info -n "$CONTAINER" -s | grep -q RUNNING || fail "$CONTAINER didn't start"

step "Listing containers"
api GET /agents | field '[a["agent_name"] for a in d["data"]["agents"]]' | grep -q "$CONTAINER" || fail "$CONTAINER not listed"

step "Attack simulations write real log lines in the container"
for PROFILE in auth_bruteforce web_attacks; do
    SIM="$(api POST /simulations/start "{\"profile_id\":\"$PROFILE\",\"duration\":3,\"eps_target\":5,\"agent_selector\":{\"agent_ids\":[\"$CONTAINER\"]}}" | field 'd["data"]["simulation_id"]')"
    for _ in $(seq 30); do
        STATUS="$(api GET /simulations | field "[s['status'] for s in d['data']['simulations'] if s['simulation_id'] == '$SIM'][0]")"
        [ "$STATUS" = running ] || break
        sleep 1
    done
    [ "$STATUS" = completed ] || { api GET /simulations >&2; fail "$PROFILE simulation ended as $STATUS"; }
    EVENTS="$(api GET /simulations | field "[s['events_generated'] for s in d['data']['simulations'] if s['simulation_id'] == '$SIM'][0]")"
    [ "$EVENTS" -ge 5 ] || fail "$PROFILE wrote $EVENTS events"
done
lxc-attach -n "$CONTAINER" -- grep -Eq '^[A-Z][a-z]{2} [ 0-9][0-9] [0-9:]{8} [^ ]+ sshd\[[0-9]+\]: Failed password for invalid user' /var/log/auth.log \
    || fail "no syslog-format brute force lines in /var/log/auth.log"
lxc-attach -n "$CONTAINER" -- grep -q 'HTTP/1.1" [0-9]' /var/log/apache2/access.log || fail "no web attack lines"

step "Deploying a Debian 12 container (the other image family)"
RESULT="$(api POST /agents/deploy "{\"count\":1,\"siem_type\":\"none\",\"os_type\":\"debian_12\",\"agent_base_name\":\"$NAME-deb\",\"deployment_id\":\"itest-2\"}")"
echo "$RESULT" | field 'd["success"]' | grep -qx True || { echo "$RESULT" >&2; fail "Debian 12 deployment failed"; }
DEBIAN="$(echo "$RESULT" | field 'd["data"]["deployed_agents"][0]["agent_name"]')"
lxc-attach -n "$DEBIAN" -- cat /etc/os-release | grep -q bookworm || fail "not a Debian 12 container"
api DELETE "/agents/$DEBIAN" >/dev/null

step "Full backup, then verify it"
BACKUP="$(api POST /system/backups | field 'd["data"]["backup"]["name"]')"
habeny backup verify "$DATA_DIR/backups/$BACKUP"
habeny backup list

step "Audit trail: recorded and intact"
habeny audit verify
habeny audit export --action container_deployment_completed | grep -q '"user": "admin"' || fail "audit entry"

step "Deleting the container"
api DELETE "/agents/$CONTAINER" >/dev/null
! lxc-ls | tr -s ' \n' '\n' | grep -qx "$CONTAINER" || fail "$CONTAINER still exists"

step "Restarting the service keeps state (graceful stop, migrations, sign-in)"
systemctl restart habeny
for _ in $(seq 60); do
    curl -sk --max-time 2 "$BASE/system/health" >/dev/null && break
    sleep 1
done
api GET /auth/status | field 'd["data"]["user"]["username"]' | grep -qx admin || fail "session lost across restart"

echo; echo "Integration test passed"
