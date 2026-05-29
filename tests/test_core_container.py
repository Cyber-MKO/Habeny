"""
Tests for container helper functions (currently in utils.py).

These pure functions don't need LXC at runtime.  We skip the entire
module if the lxc C-extension isn't installed.
"""
import pytest

utils = pytest.importorskip("utils", reason="utils.py requires python-lxc")

parse_memory_limit = utils.parse_memory_limit
validate_container_name = utils.validate_container_name


def test_parse_memory_limit_megabytes():
    assert parse_memory_limit("512MB") == str(512 * 1024 * 1024)


def test_parse_memory_limit_gigabytes():
    assert parse_memory_limit("2GB") == str(2 * 1024 * 1024 * 1024)


def test_parse_memory_limit_raw_number():
    assert parse_memory_limit(1048576) == "1048576"


def test_parse_memory_limit_invalid_returns_default():
    assert parse_memory_limit("???") == "536870912"


def test_validate_container_name_valid():
    assert validate_container_name("my-container.01") is True


def test_validate_container_name_rejects_leading_dash():
    assert validate_container_name("-bad") is False


def test_validate_container_name_rejects_too_long():
    assert validate_container_name("a" * 51) is False
