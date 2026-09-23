"""
Values that reach agent install scripts or host paths must be inert: strict formats,
checked both on the request models and inside the installers.
"""
import subprocess

import pytest

from app.core.validation import (
    validate_container_path,
    validate_group,
    validate_host,
    validate_token,
    validate_version,
)

HOSTILE = ["a;id", "$(id)", "`id`", "a b", "a'b", 'a"b', "a|e", "a&b", "a\nb", "../x", "", "-rf"]


@pytest.mark.parametrize("check,good", [
    (validate_host, ["10.0.0.5", "wazuh.example.com", "fleet-01.local"]),
    (validate_version, ["4.14.2", "9.0.2", "4.7.0-1"]),
    (validate_group, ["default", "linux-servers", "team_a.prod"]),
    (validate_token, ["AbC123", "dG9rZW46c2VjcmV0==", "a.b_c:d-e+/f"]),
])
def test_accepts_legitimate_values(check, good):
    for value in good:
        assert check(value) == value


@pytest.mark.parametrize("check", [validate_host, validate_version, validate_group, validate_token])
@pytest.mark.parametrize("value", HOSTILE)
def test_rejects_shell_and_path_syntax(check, value):
    if check is validate_token and value == "../x":
        pytest.skip("tokens may contain / and . (base64); they are only ever quoted values, never paths")
    with pytest.raises(ValueError):
        check(value)


@pytest.mark.parametrize("path", ["/var/log/x;id", "/var/log/../../etc/shadow", "relative/x", "/tmp/a b", "/tmp/$(id)"])
def test_rejects_unsafe_container_paths(path):
    with pytest.raises(ValueError):
        validate_container_path(path)


def test_log_content_is_written_verbatim_never_executed(tmp_path):
    container = pytest.importorskip("app.core.container")
    canary = tmp_path / "PWNED"
    target = tmp_path / "logs" / "app.log"
    content = f"a\nEOFLOG\ntouch {canary}\n$(touch {canary}) `touch {canary}` 'q' \"dq\" \\ end\nünïcode\n"
    script = container.build_write_file_script(str(target), content)
    subprocess.run(["bash", "-euc", script], check=True)
    assert target.read_text() == content
    assert not canary.exists()


def test_models_reject_injection():
    models = pytest.importorskip("app.models")
    with pytest.raises(ValueError):
        models.AgentDeploymentRequest(count=1, siem_type="utmstack", siem_ip="1.2.3.4", siem_auth_key='k"; reboot; "')
    with pytest.raises(ValueError):
        models.BenchmarkStartRequest(siem_version="../../../etc/cron.d/x")
    with pytest.raises(ValueError):
        models.ManagerProfileCreate(name="p", siem_type="wazuh", siem_ip="$(id)")
