"""
Configuration: every setting Habeny reads, declared once with its type, default and
description (SETTINGS below).

Values come from, highest priority first:
  1. environment variables (HABENY_*)
  2. the config file: HABENY_CONFIG, default /etc/habeny/habeny.conf
     (KEY=value lines, the same format as a systemd EnvironmentFile)
  3. the defaults below

`habeny config` shows the effective values and where each came from; README's
"Configuration" table and deploy/habeny.conf.example are checked against SETTINGS
by the tests, so they can't drift.
"""
import logging
import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = "/etc/habeny/habeny.conf"


class ConfigError(ValueError):
    pass


# ── value types ─────────────────────────────────────────────────────────

def _int(minimum: int | None = None, maximum: int | None = None) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise ConfigError(f"expected a whole number, got {raw!r}") from None
        if minimum is not None and value < minimum:
            raise ConfigError(f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ConfigError(f"must be at most {maximum}")
        return value
    return parse


def _choice(*options: str) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        value = raw.strip().lower()
        if value not in options:
            raise ConfigError(f"must be one of {', '.join(options)}; got {raw!r}")
        return value
    return parse


def _bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off", ""):
        return False
    raise ConfigError(f"expected true/false, got {raw!r}")


def _list(raw: str) -> list[str]:
    return [v.strip() for v in raw.split(",") if v.strip()]


def _origins(raw: str) -> list[str]:
    origins = [o.rstrip("/") for o in _list(raw)]
    if "*" in origins:
        raise ConfigError("must list exact origins; '*' is not allowed")
    for origin in origins:
        if not origin.startswith(("http://", "https://")):
            raise ConfigError(f"{origin!r} isn't an origin like https://host:port")
    return origins


def _str(raw: str) -> str:
    return raw.strip()


def _path(raw: str) -> Path:
    return Path(raw.strip())


# ── the settings ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Setting:
    name: str
    default: str
    help: str
    group: str
    parse: Callable[[str], Any] = _str
    secret: bool = False
    installer: bool = False  # set in the systemd units by the installer; change by reinstalling


_CPUS = cpu_count()

SETTINGS: list[Setting] = [
    # Server
    Setting("HABENY_HOST", "0.0.0.0", "Address to listen on", "Server"),
    Setting("HABENY_PORT", "9000", "Port to listen on", "Server", _int(1, 65535)),
    Setting("HABENY_TLS", "auto", "`auto`: HTTPS (your certificate, else self-signed); `off`: plain HTTP "
            "behind a reverse proxy that terminates TLS", "Server", _choice("auto", "off")),
    Setting("HABENY_TLS_CERT", "", "Your certificate (PEM, full chain)", "Server", _str),
    Setting("HABENY_TLS_KEY", "", "Its private key (PEM)", "Server", _str),
    Setting("HABENY_FORWARDED_ALLOW_IPS", "127.0.0.1", "Reverse proxies trusted to send X-Forwarded-Proto/-For "
            "(comma-separated IPs, or `*`)", "Server"),
    Setting("HABENY_LOG_LEVEL", "INFO", "Log level", "Server", _choice("debug", "info", "warning", "error")),
    Setting("HABENY_SHUTDOWN_TIMEOUT", "600", "Seconds a stop/restart waits for running deployments to "
            "finish before interrupting them (the systemd unit allows up to 840)", "Server", _int(0, 840)),
    # Capacity
    Setting("HABENY_DEPLOY_WORKERS", str(_CPUS), "Containers deployed in parallel (default: CPU count)",
            "Capacity", _int(1, 256)),
    Setting("HABENY_BENCHMARK_WORKERS", str(_CPUS), "Parallel workers for benchmark runs (default: CPU count)",
            "Capacity", _int(1, 256)),
    # Accounts and access
    Setting("HABENY_SESSION_TTL_HOURS", "168", "How long a sign-in lasts (hours)", "Accounts", _int(1, 24 * 365)),
    Setting("HABENY_PASSWORD_MIN_LENGTH", "12", "Minimum password length", "Accounts", _int(8, 128)),
    Setting("HABENY_CORS_ORIGINS", "", "Other browser origins allowed to call the API, comma-separated "
            "(exact `https://host:port`); empty: none", "Accounts", _origins),
    Setting("HABENY_SECRET_KEY", "", "Key encrypting stored SIEM secrets (default: generated in "
            "`DATA_DIR/secret.key`)", "Accounts", _str, secret=True),
    # Single sign-on
    Setting("HABENY_OIDC_ISSUER", "", "OIDC issuer URL; turns single sign-on on", "Single sign-on"),
    Setting("HABENY_OIDC_CLIENT_ID", "", "Client ID from the app registration", "Single sign-on"),
    Setting("HABENY_OIDC_CLIENT_SECRET", "", "Client secret", "Single sign-on", secret=True),
    Setting("HABENY_OIDC_REDIRECT_URI", "", "Redirect URI registered at the provider (set it behind a "
            "reverse proxy)", "Single sign-on"),
    Setting("HABENY_OIDC_SCOPES", "openid profile email", "Scopes to request", "Single sign-on"),
    Setting("HABENY_OIDC_USERNAME_CLAIM", "preferred_username", "Claim used as the username",
            "Single sign-on"),
    Setting("HABENY_OIDC_GROUPS_CLAIM", "groups", "Claim listing the user's groups", "Single sign-on"),
    Setting("HABENY_OIDC_ADMIN_GROUPS", "", "Groups whose members are admins (comma-separated)",
            "Single sign-on", _list),
    Setting("HABENY_OIDC_OPERATOR_GROUPS", "", "Groups whose members are operators", "Single sign-on", _list),
    Setting("HABENY_OIDC_VIEWER_GROUPS", "", "Groups whose members are viewers", "Single sign-on", _list),
    Setting("HABENY_OIDC_DEFAULT_ROLE", "viewer", "Role for new SSO users when no group mapping is set",
            "Single sign-on", _choice("viewer", "operator", "admin")),
    Setting("HABENY_OIDC_BUTTON_LABEL", "Sign in with SSO", "Sign-in button text", "Single sign-on"),
    Setting("HABENY_OIDC_CA_BUNDLE", "", "CA file for a provider with a private certificate",
            "Single sign-on"),
    Setting("HABENY_OIDC_ALLOW_HTTP", "false", "Allow a plain-HTTP provider (testing only)", "Single sign-on",
            _bool),
    # Set by the installer
    Setting("HABENY_DATA_DIR", "/var/lib/lxc-siem-platform", "Database, keys, reports and logs",
            "Installation", _path, installer=True),
    Setting("HABENY_LXC_BACKEND", "", "`helper` (unprivileged app + root helper) or `direct` (app runs as "
            "root); default: direct when root, else helper", "Installation", _choice("", "helper", "direct"),
            installer=True),
    Setting("HABENY_HELPER_SOCKET", "/run/habeny/helper.sock", "The helper's Unix socket", "Installation",
            installer=True),
    Setting("HABENY_HELPER_USER", "habeny", "The only user (besides root) the helper accepts", "Installation",
            installer=True),
]
BY_NAME = {s.name: s for s in SETTINGS}
# Read from the environment but not configuration in their own right
_OTHER_KNOWN = {"HABENY_CONFIG", "HABENY_INSTALL_DIR", "HABENY_LXC_ATTACH", "HABENY_HELPER_LOG_LEVEL"}


# ── config file ─────────────────────────────────────────────────────────

def config_file() -> Path:
    return Path(os.environ.get("HABENY_CONFIG", DEFAULT_CONFIG_FILE))


def parse_config_file(text: str) -> dict[str, str]:
    """KEY=value lines; '#' comments, optional 'export ' and shell-style quotes."""
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, raw = line.partition("=")
        key = key.strip()
        if not sep or not key.isidentifier():
            raise ConfigError(f"line {number}: expected KEY=value")
        try:
            parts = shlex.split(raw, comments=True)
        except ValueError as e:
            raise ConfigError(f"line {number}: {e}") from None
        values[key] = " ".join(parts)
    return values


FILE_VALUES: dict[str, str] = {}  # what the config file set (for `habeny config`)


def load_config_file() -> None:
    """Merge the config file into os.environ; variables already set win."""
    path = config_file()
    try:
        text = path.read_text()
    except FileNotFoundError:
        if "HABENY_CONFIG" in os.environ:
            raise ConfigError(f"HABENY_CONFIG points to {path}, which doesn't exist") from None
        return
    except PermissionError:
        logger.warning(f"Can't read {path} (permission denied); using environment and defaults only")
        return
    try:
        values = parse_config_file(text)
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from None
    for key, value in values.items():
        if key not in BY_NAME and key not in _OTHER_KNOWN:
            logger.warning(f"{path}: unknown setting {key} (ignored; see `habeny config`)")
            continue
        FILE_VALUES[key] = value
        os.environ.setdefault(key, value)


# ── reading values ──────────────────────────────────────────────────────

def raw(name: str) -> str:
    return os.environ.get(name, BY_NAME[name].default)


def get(name: str) -> Any:
    """The typed, validated value of a setting (read at call time)."""
    setting = BY_NAME[name]
    try:
        return setting.parse(raw(name))
    except ConfigError as e:
        raise ConfigError(f"{name}: {e}") from None


def source(name: str) -> str:
    if name not in os.environ:
        return "default"
    if name in FILE_VALUES and os.environ[name] == FILE_VALUES[name]:
        return str(config_file())
    return "environment"


def validate() -> list[str]:
    """Every problem with the current configuration (empty: fine)."""
    problems = []
    for setting in SETTINGS:
        try:
            get(setting.name)
        except ConfigError as e:
            problems.append(str(e))
    if bool(raw("HABENY_TLS_CERT")) != bool(raw("HABENY_TLS_KEY")):
        problems.append("HABENY_TLS_CERT and HABENY_TLS_KEY must be set together")
    for name in ("HABENY_TLS_CERT", "HABENY_TLS_KEY", "HABENY_OIDC_CA_BUNDLE"):
        if raw(name) and not Path(raw(name)).is_file():
            problems.append(f"{name}: file {raw(name)} not found")
    if raw("HABENY_OIDC_ISSUER") and not raw("HABENY_OIDC_CLIENT_ID"):
        problems.append("HABENY_OIDC_ISSUER is set but HABENY_OIDC_CLIENT_ID is not")
    return problems


def check() -> None:
    problems = validate()
    if problems:
        raise ConfigError("Invalid configuration:\n  " + "\n  ".join(problems)
                          + f"\n(config file: {config_file()}; `habeny config` shows all settings)")


load_config_file()

# ── values used across the app (fixed at startup) ──────────────────────

DATA_DIR = get("HABENY_DATA_DIR")
CONFIGS_DIR = DATA_DIR / "configs"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"
AGENTS_DIR = DATA_DIR / "agents"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "platform.db"

# Built React frontend (see frontend/vite.config.js build.outDir)
STATIC_DIR = ROOT_DIR / "static"

SESSION_COOKIE = "habeny_session"
SESSION_TTL_HOURS = get("HABENY_SESSION_TTL_HOURS")
CORS_ORIGINS = get("HABENY_CORS_ORIGINS")
DEPLOY_WORKERS = get("HABENY_DEPLOY_WORKERS")
BENCHMARK_WORKERS = get("HABENY_BENCHMARK_WORKERS")
SHUTDOWN_TIMEOUT = get("HABENY_SHUTDOWN_TIMEOUT")
