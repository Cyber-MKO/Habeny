"""
Attack simulation profiles write realistic log lines (the formats SIEM agents parse), every
profile the UI offers is implemented, and event counts are the lines actually written.
"""
import asyncio
import re
import subprocess

import pytest

from app.services import simulation
from app.state import simulations_db

SYSLOG = re.compile(r"^[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} \S+ \S+(\[\d+\])?: .+")
APACHE = re.compile(r'^203\.0\.113\.7 - - \[\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}\] "[A-Z]+ \S+ HTTP/1\.1" '
                    r'\d{3} \d+ "-" ".+"$')


def _run(profile, tmp_path, count=12):
    script = simulation.build_attack_script(profile, count, "203.0.113.7", str(tmp_path))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    logs = {p.relative_to(tmp_path / "var/log").as_posix(): p.read_text().splitlines()
            for p in (tmp_path / "var/log").rglob("*") if p.is_file()}
    return out.stdout, logs


@pytest.mark.parametrize("profile", sorted(simulation.PROFILES))
def test_every_profile_writes_parseable_lines(profile, tmp_path):
    stdout, logs = _run(profile, tmp_path)
    assert "EVENTS_WRITTEN=12" in stdout
    assert sum(len(lines) for lines in logs.values()) == 12  # the count is what was written
    for name, lines in logs.items():
        pattern = APACHE if name.startswith("apache2/") else SYSLOG
        bad = [line for line in lines if not pattern.match(line)]
        assert not bad, f"{profile}: {name} has unparseable lines: {bad[:2]}"
        assert "$(" not in "".join(lines)  # no unexpanded shell


def test_profiles_carry_their_indicators(tmp_path):
    checks = {
        "auth_bruteforce": ("auth.log", "Failed password for invalid user", "from 203.0.113.7"),
        "web_attacks": ("apache2/access.log", "203.0.113.7", "HTTP/1.1"),
        "malware_beacon": ("syslog", "[UFW BLOCK]", "DST=198.51.100.66"),
        "lateral_movement": ("auth.log", "Accepted password for svc_backup from 10.", "session opened"),
        "data_exfiltration": ("auth.log", "COMMAND=/usr/bin/tar czf", "COMMAND=/usr/bin/scp"),
        "privilege_escalation": ("auth.log", "user NOT in sudoers", "FAILED SU (to root)"),
    }
    for profile, (log, *needles) in checks.items():
        _, logs = _run(profile, tmp_path / profile)
        text = "\n".join(logs[log])
        for needle in needles:
            assert needle in text, f"{profile}: {needle!r} missing from {log}"


def test_ui_profiles_match_the_backend():
    """The Simulations page lists exactly the implemented profiles."""
    from pathlib import Path
    page = (Path(__file__).resolve().parents[2] / "frontend/src/pages/Simulations.jsx").read_text()
    offered = set(re.findall(r'\{ id: "(\w+)"', page))
    assert offered == set(simulation.PROFILES)


def test_script_inputs_are_checked():
    with pytest.raises(ValueError):
        simulation.build_attack_script("port_scan", 1, "203.0.113.7")
    with pytest.raises(ValueError):
        simulation.build_attack_script("auth_bruteforce", 1, "1.2.3.4; rm -rf /")


def test_event_counts_come_from_the_container(monkeypatch):
    replies = {"good": {"success": True, "stdout": "EVENTS_WRITTEN=5\n"},
               "broken": {"success": False, "stdout": "", "stderr": "bash: /var/log/auth.log: Read-only file system"}}
    monkeypatch.setattr(simulation, "execute_in_container", lambda name, script, timeout: replies[name])
    assert simulation.generate_simulation_events("good", "auth_bruteforce", 5) == {"success": True, "events": 5, "error": None}
    bad = simulation.generate_simulation_events("broken", "auth_bruteforce", 5)
    assert bad["events"] == 0 and "Read-only" in bad["error"]


def test_run_reports_real_totals_and_fails_when_nothing_is_written(monkeypatch):
    monkeypatch.setattr(simulation, "execute_in_container",
                        lambda name, script, timeout: {"success": True, "stdout": "EVENTS_WRITTEN=3"} if name == "ok"
                        else {"success": False, "stdout": "", "stderr": "no such file"})
    monkeypatch.setattr(simulation, "announce_finished", lambda sim_id: None)
    simulations_db["sim-real"] = {"simulation_id": "sim-real", "status": "running"}
    simulations_db["sim-dead"] = {"simulation_id": "sim-dead", "status": "running"}
    try:
        asyncio.run(simulation.run_simulation("sim-real", "auth_bruteforce", ["ok", "bad"], 1, 3))
        real = simulations_db["sim-real"]
        assert real["status"] == "completed" and real["events_generated"] == 3 and real["failed_writes"] == 1
        assert real["attacker_ip"].startswith("203.0.113.")
        asyncio.run(simulation.run_simulation("sim-dead", "auth_bruteforce", ["bad"], 1, 3))
        dead = simulations_db["sim-dead"]
        assert dead["status"] == "failed" and dead["events_generated"] == 0 and "no such file" in dead["error"]
    finally:
        simulations_db.pop("sim-real", None)
        simulations_db.pop("sim-dead", None)


def test_removed_options_are_refused_or_ignored(client):
    # the four profiles that were never implemented
    for profile in ("port_scan", "sql_injection", "xss_attack", "ddos_attack"):
        assert client.post("/simulations/start", json={"profile_id": profile,
                                                       "agent_selector": {"count": 1}}).status_code == 422
    # intensity/burst/custom parameters did nothing; old clients sending them still work
    resp = client.post("/simulations/start", json={"profile_id": "auth_bruteforce", "intensity": "high",
                                                   "burst_mode": True, "agent_selector": {"agent_ids": ["none-such"]}})
    assert resp.status_code == 400  # past validation: no matching containers
    # tags can't be set on containers, so they're no longer a selector
    assert client.post("/simulations/start", json={"profile_id": "auth_bruteforce",
                                                   "agent_selector": {"tags": ["x"]}}).status_code == 422
