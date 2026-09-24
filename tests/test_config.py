"""
Configuration: the config file, precedence, validation, and that the docs and the
example file list exactly the settings the code reads.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import cli, config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def env():
    """Restore os.environ afterwards (load_config_file writes to it)."""
    saved = dict(os.environ)
    config.FILE_VALUES.clear()
    yield os.environ
    os.environ.clear()
    os.environ.update(saved)
    config.FILE_VALUES.clear()


def test_parse_config_file():
    values = config.parse_config_file(
        "# comment\n\nHABENY_PORT=9443\nexport HABENY_TLS=off\n"
        "HABENY_OIDC_BUTTON_LABEL=\"Sign in with Okta\"  # trailing comment\nHABENY_CORS_ORIGINS=\n"
    )
    assert values == {"HABENY_PORT": "9443", "HABENY_TLS": "off",
                      "HABENY_OIDC_BUTTON_LABEL": "Sign in with Okta", "HABENY_CORS_ORIGINS": ""}
    with pytest.raises(config.ConfigError, match="line 1"):
        config.parse_config_file("not a setting")
    with pytest.raises(config.ConfigError, match="line 2"):
        config.parse_config_file("A=1\nB=\"unterminated")


def test_file_values_apply_and_environment_wins(env, tmp_path, caplog):
    conf = tmp_path / "habeny.conf"
    conf.write_text("HABENY_PORT=9443\nHABENY_LOG_LEVEL=debug\nHABENY_TYPO=1\n")
    env["HABENY_CONFIG"] = str(conf)
    env.pop("HABENY_PORT", None)
    env["HABENY_LOG_LEVEL"] = "warning"
    config.load_config_file()
    assert config.get("HABENY_PORT") == 9443 and config.source("HABENY_PORT") == str(conf)
    assert config.get("HABENY_LOG_LEVEL") == "warning" and config.source("HABENY_LOG_LEVEL") == "environment"
    assert config.source("HABENY_HOST") == "default"
    assert "unknown setting HABENY_TYPO" in caplog.text
    assert "HABENY_TYPO" not in env


def test_missing_explicit_config_file_is_an_error(env, tmp_path):
    env["HABENY_CONFIG"] = str(tmp_path / "nope.conf")
    with pytest.raises(config.ConfigError, match="doesn't exist"):
        config.load_config_file()


@pytest.mark.parametrize("name,value,message", [
    ("HABENY_PORT", "http", "whole number"),
    ("HABENY_PORT", "70000", "at most 65535"),
    ("HABENY_TLS", "on", "one of auto, off"),
    ("HABENY_CORS_ORIGINS", "*", "'*' is not allowed"),
    ("HABENY_CORS_ORIGINS", "example.com", "isn't an origin"),
    ("HABENY_DEPLOY_WORKERS", "0", "at least 1"),
    ("HABENY_OIDC_ALLOW_HTTP", "maybe", "true/false"),
    ("HABENY_TLS_CERT", "/nonexistent/cert.pem", "must be set together"),
])
def test_invalid_values_are_reported(env, name, value, message):
    env[name] = value
    problems = config.validate()
    assert any(name in p and message in p for p in problems) or any(message in p for p in problems), problems


def test_all_problems_reported_at_once(env):
    env["HABENY_PORT"] = "x"
    env["HABENY_TLS"] = "maybe"
    with pytest.raises(config.ConfigError) as exc:
        config.check()
    assert "HABENY_PORT" in str(exc.value) and "HABENY_TLS" in str(exc.value)


def test_server_refuses_to_start_with_bad_config(tmp_path):
    result = subprocess.run(
        [sys.executable, "main.py"], cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "HABENY_PORT": "not-a-port", "HABENY_DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 78, result.stderr  # the systemd unit won't restart-loop on this
    assert "HABENY_PORT" in result.stderr and "Traceback" not in result.stderr


def test_every_setting_the_code_reads_is_registered():
    pattern = re.compile(r"HABENY_[A-Z0-9_]+")
    used = set()
    for path in [*(ROOT / "app").rglob("*.py"), ROOT / "main.py"]:
        used |= set(pattern.findall(path.read_text()))
    # names built at runtime (f"HABENY_OIDC_{role}_GROUPS") and ones that aren't settings
    used -= {"HABENY_OIDC_", "HABENY_"}
    unregistered = used - set(config.BY_NAME) - config._OTHER_KNOWN
    assert not unregistered, f"add these to app/config.py SETTINGS: {sorted(unregistered)}"


def test_admin_guide_lists_every_setting():
    guide = (ROOT / "docs" / "admin-guide.md").read_text()
    assert cli.docs_table() in guide, "docs/admin-guide.md's configuration table is out of date: run `habeny config docs`"


def test_example_config_is_current():
    example = (ROOT / "deploy" / "habeny.conf.example").read_text()
    assert example == cli.example_config(), "run: python -m app.cli config example > deploy/habeny.conf.example"
    # and it parses: every line is a comment
    assert config.parse_config_file(example) == {}
