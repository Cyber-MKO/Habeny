"""
Tests for shell command execution (app/core/shell.py).

These tests mock subprocess so they run without root or LXC.
"""
import pytest

module = pytest.importorskip("app.core.shell", reason="requires python-lxc")

run_command = module.run_command


def test_run_command_captures_stdout():
    result = run_command(["echo", "hello"])
    assert result["success"] is True
    assert result["stdout"] == "hello"


def test_run_command_returns_failure_on_bad_command():
    result = run_command(["false"])
    assert result["success"] is False


def test_run_command_handles_timeout():
    result = run_command(["sleep", "60"], timeout=1)
    assert result["success"] is False
    assert "timeout" in result.get("error", "").lower()
