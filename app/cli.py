"""
`habeny`: administration commands. Installed as /usr/local/bin/habeny, which runs this
as the service user with the service's settings.

  habeny version
  habeny config [check|example|docs]
  habeny db status|migrate|backup|restore FILE|downgrade --to N
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app import config

EX_CONFIG = 78


def _mask(setting: config.Setting, value: str) -> str:
    if setting.secret and value:
        return "(set, hidden)"
    return value if value != "" else "(empty)"


def cmd_version(args) -> int:
    from app.migrations import latest_version
    from app.version import __version__
    print(f"Habeny {__version__} (database schema v{latest_version()})")
    return 0


def cmd_config(args) -> int:
    if args.action == "check":
        problems = config.validate()
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if problems:
            return EX_CONFIG
        print(f"Configuration OK (file: {config.config_file()}"
              f"{'' if config.config_file().exists() else ', not present: defaults and environment only'})")
        return 0
    if args.action == "example":
        print(example_config(), end="")
        return 0
    if args.action == "docs":
        print(docs_table(), end="")
        return 0
    print(f"# config file: {config.config_file()}{'' if config.config_file().exists() else ' (not present)'}")
    width = max(len(s.name) for s in config.SETTINGS)
    group = None
    for setting in config.SETTINGS:
        if setting.group != group:
            group = setting.group
            print(f"\n[{group}]")
        print(f"{setting.name:<{width}}  {_mask(setting, config.raw(setting.name)):<30}  "
              f"({config.source(setting.name)})")
    problems = config.validate()
    if problems:
        print("\nProblems:\n  " + "\n  ".join(problems), file=sys.stderr)
        return EX_CONFIG
    return 0


def example_config() -> str:
    """deploy/habeny.conf.example: every setting, commented out, with its default."""
    lines = [
        "# Habeny configuration: /etc/habeny/habeny.conf",
        "# KEY=value lines. Environment variables override this file; `habeny config`",
        "# shows the values in effect. Restart after changing: sudo systemctl restart habeny",
        "# Generated from app/config.py (`habeny config example`); every setting is listed",
        "# with its default.",
    ]
    group = None
    for setting in config.SETTINGS:
        if setting.installer:
            continue
        if setting.group != group:
            group = setting.group
            lines += ["", f"# ── {group} " + "─" * max(0, 60 - len(group))]
        lines.append(f"# {setting.help.replace('`', '')}")
        lines.append(f"#{setting.name}={setting.default}")
    lines += ["", "# Set by the installer in the systemd units (reinstall to change):"]
    lines += [f"#   {s.name} (default {s.default or 'automatic'})" for s in config.SETTINGS if s.installer]
    return "\n".join(lines) + "\n"


def docs_table() -> str:
    """The README's configuration table."""
    rows = ["| Setting | Default | Description |", "|---|---|---|"]
    for setting in config.SETTINGS:
        default = f"`{setting.default}`" if setting.default else ""
        if setting.name in ("HABENY_DEPLOY_WORKERS", "HABENY_BENCHMARK_WORKERS"):
            default = "CPU count"
        note = " *(set by the installer)*" if setting.installer else ""
        rows.append(f"| `{setting.name}` | {default} | {setting.help}{note} |")
    return "\n".join(rows) + "\n"


def _service_active() -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(["systemctl", "is-active", "--quiet", "habeny"], check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def cmd_db(args) -> int:
    from app import migrations
    db = config.DB_PATH
    if args.action == "status":
        info = migrations.status(db)
        print(f"Database:  {info['database']}")
        print(f"Schema:    v{info['current']} (this Habeny: v{info['latest']})")
        if info["too_new"]:
            print("           newer than this Habeny: upgrade Habeny, or restore a backup")
        for line in info["pending"]:
            print(f"Pending:   {line}")
        print("Backups:   " + ("\n           ".join(info["backups"]) if info["backups"] else "none"))
        return 0
    if args.action == "backup":
        print(migrations.backup(db))
        return 0
    if args.action == "migrate":
        applied = migrations.migrate(db)
        print(f"Migrated to v{applied[-1].version}" if applied else "Already up to date")
        return 0
    # restore and downgrade replace data the running app is using
    if _service_active() and not args.force:
        print("error: Habeny is running. Stop it first (sudo systemctl stop habeny), or pass --force.",
              file=sys.stderr)
        return 1
    if args.action == "restore":
        version = migrations.restore(db, Path(args.file))
        print(f"Restored {args.file} (schema v{version}). The replaced database was backed up first.")
        if version < migrations.latest_version():
            print(f"This Habeny will migrate it to v{migrations.latest_version()} when it starts; to keep v{version}, "
                  "install the Habeny version it came from.")
        return 0
    if args.action == "downgrade":
        steps = migrations.downgrade(db, args.to)
        print(f"Downgraded to v{args.to} (undid {', '.join(f'v{m.version}' for m in steps)}). Install the "
              "matching Habeny version before starting it; this one would migrate it again.")
        return 0
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="habeny", description="Habeny administration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="show the version")

    p_config = sub.add_parser("config", help="show settings and where they come from")
    p_config.add_argument("action", nargs="?", choices=["show", "check", "example", "docs"], default="show")

    p_db = sub.add_parser("db", help="database schema, backups and restores")
    db_sub = p_db.add_subparsers(dest="action", required=True)
    db_sub.add_parser("status", help="schema version, pending migrations, backups")
    db_sub.add_parser("migrate", help="apply pending migrations (backs up first)")
    db_sub.add_parser("backup", help="back up the database now")
    p_restore = db_sub.add_parser("restore", help="replace the database with a backup (stop Habeny first)")
    p_restore.add_argument("file")
    p_restore.add_argument("--force", action="store_true", help="even if the service is running")
    p_down = db_sub.add_parser("downgrade", help="undo migrations (where they support it)")
    p_down.add_argument("--to", type=int, required=True)
    p_down.add_argument("--force", action="store_true", help="even if the service is running")

    args = parser.parse_args(argv)
    handlers = {"version": cmd_version, "config": cmd_config, "db": cmd_db}
    try:
        return handlers[args.command](args)
    except BrokenPipeError:  # output piped into e.g. head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())  # no second error at exit
        return 0
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return EX_CONFIG
    except Exception as e:  # MigrationError and friends: a message, not a traceback
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
