"""
Strict formats for values that end up in shell scripts run inside containers or in
host file paths (agent package cache). Anything outside these character sets is
rejected, so a value can never be parsed as shell syntax, a sed delimiter or a path
component. Used by the request models (clear 422s) and again by the installers
themselves, whatever the entry point.
"""
import re

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_IPV4 = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")
_VERSION = re.compile(r"^\d{1,4}(\.\d{1,4}){1,3}(-[A-Za-z0-9]{1,16})?$")        # 4.14.2, 9.0.2, 4.7.0-1
_GROUP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+/=_.:-]{0,1023}$")                  # API keys, base64 tokens; never starts with "-" (option injection)
_CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PATH = re.compile(r"^/[A-Za-z0-9_.@+/-]{0,4095}$")


def _check(value: str | None, pattern: re.Pattern, what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {what}: {value!r}")
    return value


def validate_host(value: str | None) -> str:
    """IPv4 address or DNS hostname."""
    if isinstance(value, str) and (_IPV4.fullmatch(value) or _HOST.fullmatch(value)):
        return value
    raise ValueError(f"Invalid host (expected an IPv4 address or hostname): {value!r}")


def validate_version(value: str | None) -> str:
    return _check(value, _VERSION, "version (expected e.g. 4.14.2)")


def validate_group(value: str | None) -> str:
    return _check(value, _GROUP, "group (letters, digits, '.', '_', '-')")


def validate_token(value: str | None) -> str:
    return _check(value, _TOKEN, "key/token (letters, digits and + / = _ . : -)")


def validate_container_name(value: str | None) -> str:
    return _check(value, _CONTAINER, "container name")


def validate_container_path(value: str | None) -> str:
    """Absolute path inside a container: no spaces, quotes or shell characters, no '..'."""
    _check(value, _PATH, "path (absolute; letters, digits and _ . @ + / - only)")
    if ".." in value.split("/"):
        raise ValueError("Invalid path: '..' is not allowed")
    return value
