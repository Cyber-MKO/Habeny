"""
Checking what the SIEM detected: after an attack simulation, ask the SIEM's own search API
which alerts it raised for the target containers, and compare them with what the profile
should trigger.

Supported, both through the Elasticsearch-compatible `_search` API:
- Wazuh: alerts in the Wazuh indexer (`wazuh-alerts-*`), by `agent.name`. The expected rules
  are ids from the Wazuh ruleset (EXPECTED below).
- Elastic: detection-engine alerts (`.alerts-security.alerts-*`), by `host.name`. Which rules
  fire depends on the rules enabled in Kibana, so there are no built-in expectations; any
  alert on a target counts. Also measured: events received from the targets (`logs-*`),
  i.e. whether ingestion works at all.

The connection (URL, user and password or API key, pinned certificate for a self-signed
endpoint) is stored on the manager profile; admins set it. Containers are matched by name:
agents register with the container name (Wazuh agent name, Elastic host name).
"""
import base64
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from app.services import hosts

logger = logging.getLogger(__name__)

MAX_BODY = 8 * 1024 * 1024
SUPPORTED = ("wazuh", "elastic")

# Wazuh ruleset (4.x) rules each attack profile's log lines should trigger. A profile counts
# as detected on a container when any of them fires; the others are listed as missed.
EXPECTED: dict[str, dict[str, dict[str, str]]] = {
    "wazuh": {
        "auth_bruteforce": {"5710": "sshd: Attempt to login using a non-existent user",
                            "5712": "sshd: brute force trying to get access to the system"},
        "web_attacks": {"31103": "SQL injection attempt", "31104": "Common web attack",
                        "31105": "XSS (Cross Site Scripting) attempt"},
        "malware_beacon": {"4101": "Firewall drop event"},
        "lateral_movement": {"5715": "sshd: authentication success", "5501": "PAM: Login session opened"},
        "data_exfiltration": {"5402": "Successful sudo to ROOT executed"},
        "privilege_escalation": {"5401": "Three failed attempts to run sudo",
                                 "5405": "Unauthorized user attempted to use sudo",
                                 "5302": "User missed the password to change UID to root"},
    },
}


class DetectionError(RuntimeError):
    pass


class FingerprintNeeded(DetectionError):
    def __init__(self, fingerprint: str):
        super().__init__("The SIEM's certificate isn't from a trusted authority. Check this fingerprint and confirm "
                         f"it: {fingerprint}")
        self.fingerprint = fingerprint


BACKENDS = {
    "wazuh": {"index": "wazuh-alerts-*", "time": "timestamp", "host": "agent.name", "rule_id": "rule.id",
              "rule_name": "rule.description", "level": "rule.level", "technique": "rule.mitre.id",
              "events_index": None},
    "elastic": {"index": ".alerts-security.alerts-*", "time": "@timestamp", "host": "host.name",
                "rule_id": "kibana.alert.rule.uuid", "rule_name": "kibana.alert.rule.name",
                "level": "kibana.alert.severity", "technique": "kibana.alert.rule.threat.technique.id",
                "events_index": "logs-*"},
}


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise DetectionError("The detection URL must be http(s)://host:port, e.g. https://wazuh-indexer:9200")
    if parts.query or parts.fragment or parts.username:
        raise DetectionError("The detection URL can't contain a query, fragment or credentials")
    return url


def configured(manager: dict | None) -> bool:
    return bool(manager and manager.get("detection_url") and manager.get("siem_type") in SUPPORTED)


def _auth_header(manager: dict) -> dict[str, str]:
    user, secret = manager.get("detection_username"), manager.get("detection_secret")
    if user and secret:
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()}
    if secret:  # Elasticsearch API key (the base64 "id:key" form Kibana shows)
        return {"Authorization": f"ApiKey {secret}"}
    return {}


def search(manager: dict, index: str, body: dict) -> dict:
    """One `_search` request, with the manager's credentials and pinned certificate."""
    url = normalize_url(manager["detection_url"])
    try:
        conn = hosts._open(url, manager.get("detection_fingerprint") or None)
    except hosts.FingerprintNeeded as e:
        raise FingerprintNeeded(e.fingerprint) from None
    except hosts.HostError as e:
        raise DetectionError(str(e)) from None
    try:
        path = (urlsplit(url).path or "") + f"/{index}/_search?ignore_unavailable=true&allow_no_indices=true"
        conn.request("POST", path, body=json.dumps(body).encode(),
                     headers={"Content-Type": "application/json", "Accept": "application/json", **_auth_header(manager)})
        resp = conn.getresponse()
        data = resp.read(MAX_BODY + 1)
    except OSError as e:
        raise DetectionError(f"{url}: {e}") from None
    finally:
        conn.close()
    if resp.status in (401, 403):
        raise DetectionError(f"The SIEM rejected the credentials (HTTP {resp.status})")
    if len(data) > MAX_BODY:
        raise DetectionError("The SIEM's answer is too large")
    try:
        payload = json.loads(data or b"{}")
    except ValueError:
        raise DetectionError(f"{url} didn't answer like Elasticsearch/OpenSearch (HTTP {resp.status})") from None
    if resp.status >= 400:
        reason = (payload.get("error") or {}).get("reason") if isinstance(payload.get("error"), dict) else payload.get("error")
        raise DetectionError(f"The SIEM refused the search (HTTP {resp.status}): {str(reason)[:200]}")
    return payload


def _window_query(fields: dict, names: list[str], start: str, end: str) -> dict:
    return {"bool": {"filter": [
        {"terms": {fields["host"]: sorted(set(names) | {n.lower() for n in names})}},
        {"range": {fields["time"]: {"gte": start, "lte": end}}},
    ]}}


def test_connection(manager: dict) -> dict[str, Any]:
    """Check the endpoint and credentials: how many alerts in the last 24 hours."""
    fields = BACKENDS[manager["siem_type"]]
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    result = search(manager, fields["index"], {"size": 0, "track_total_hits": True,
                                               "query": {"range": {fields["time"]: {"gte": since}}}})
    total = (result.get("hits") or {}).get("total") or {}
    return {"alerts_last_24h": total.get("value", 0) if isinstance(total, dict) else total}


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dig(source: dict, dotted: str) -> Any:
    value: Any = source
    for part in dotted.split("."):
        if isinstance(value, dict) and dotted in value:  # flattened keys ("kibana.alert.rule.name")
            return value[dotted]
        value = value.get(part) if isinstance(value, dict) else None
    return value


def check(manager: dict, profile_id: str, containers: list[str], started_at: str, until: str) -> dict[str, Any]:
    """What the SIEM detected for a simulation run. Raises DetectionError on connection problems."""
    siem = manager["siem_type"]
    fields = BACKENDS[siem]
    expected = EXPECTED.get(siem, {}).get(profile_id, {})
    start = _parse_time(started_at) or datetime.now(timezone.utc)
    query = _window_query(fields, containers, start.isoformat(), until)
    body = {
        "size": 0, "track_total_hits": True, "query": query,
        "aggs": {
            "hosts": {"terms": {"field": fields["host"], "size": max(10, len(containers) * 2)}, "aggs": {
                "first": {"min": {"field": fields["time"]}},
                "rules": {"terms": {"field": fields["rule_id"], "size": 100}, "aggs": {
                    "first": {"min": {"field": fields["time"]}}}},
            }},
            "rules": {"terms": {"field": fields["rule_id"], "size": 200}, "aggs": {
                "sample": {"top_hits": {"size": 1, "_source": [fields["rule_name"], fields["level"], fields["technique"]]}}}},
        },
    }
    result = search(manager, fields["index"], body)
    aggs = result.get("aggregations") or {}

    wanted = {c.lower(): c for c in containers}
    per_container: dict[str, dict[str, Any]] = {c: {"name": c, "alerts": 0, "detected": False,
                                                     "first_alert_at": None, "ttd_seconds": None}
                                                for c in containers}
    for bucket in (aggs.get("hosts") or {}).get("buckets", []):
        name = wanted.get(str(bucket["key"]).lower())
        if not name:
            continue
        row = per_container[name]
        row["alerts"] = bucket["doc_count"]
        rule_times = {str(r["key"]): _parse_time(r["first"].get("value_as_string") or r["first"].get("value"))
                      for r in (bucket.get("rules") or {}).get("buckets", [])}
        relevant = [t for rid, t in rule_times.items() if t and (not expected or rid in expected)]
        if relevant:
            first = min(relevant)
            row.update(detected=True, first_alert_at=first.isoformat(),
                       ttd_seconds=round(max(0.0, (first - start).total_seconds()), 1))

    rules = []
    for bucket in (aggs.get("rules") or {}).get("buckets", []):
        hits = ((bucket.get("sample") or {}).get("hits") or {}).get("hits") or [{}]
        source = hits[0].get("_source") or {}
        rid = str(bucket["key"])
        rules.append({"id": rid, "name": _dig(source, fields["rule_name"]) or expected.get(rid, ""),
                      "level": _dig(source, fields["level"]), "technique": _dig(source, fields["technique"]),
                      "count": bucket["doc_count"], "expected": rid in expected})
    seen = {r["id"] for r in rules}
    detected = [c for c in per_container.values() if c["detected"]]
    ttds = [c["ttd_seconds"] for c in detected if c["ttd_seconds"] is not None]
    out: dict[str, Any] = {
        "siem": siem,
        "window": {"start": start.isoformat(), "end": until},
        "containers": len(containers),
        "detected": len(detected),
        "detection_rate": round(100 * len(detected) / len(containers), 1) if containers else 0.0,
        "ttd_seconds": {"median": statistics.median(ttds), "max": max(ttds)} if ttds else None,
        "alerts": sum(c["alerts"] for c in per_container.values()),
        "rules": rules,
        "expected": [{"id": rid, "name": name, "seen": rid in seen} for rid, name in expected.items()],
        "missed": [rid for rid in expected if rid not in seen],
        "per_container": list(per_container.values()),
        "basis": "expected rules" if expected else "any alert",
    }
    if fields["events_index"]:
        out["ingestion"] = _ingestion(manager, fields, containers, start, until)
    return out


def _ingestion(manager: dict, fields: dict, containers: list[str], start: datetime, until: str) -> dict[str, Any]:
    """Events received from the targets (Elastic): proves the logs arrive even without alerts."""
    body = {"size": 0, "track_total_hits": True,
            "query": _window_query(fields, containers, start.isoformat(), until),
            "aggs": {"hosts": {"terms": {"field": fields["host"], "size": max(10, len(containers) * 2)},
                               "aggs": {"first": {"min": {"field": fields["time"]}}}}}}
    try:
        result = search(manager, fields["events_index"], body)
    except DetectionError as e:
        return {"error": str(e)}
    buckets = ((result.get("aggregations") or {}).get("hosts") or {}).get("buckets", [])
    firsts = [_parse_time(b["first"].get("value_as_string") or b["first"].get("value")) for b in buckets]
    lags = [max(0.0, (t - start).total_seconds()) for t in firsts if t]
    total = (result.get("hits") or {}).get("total") or {}
    return {"events": total.get("value", 0) if isinstance(total, dict) else total,
            "hosts_reporting": len(buckets),
            "first_event_seconds": {"median": statistics.median(lags), "max": max(lags)} if lags else None}
