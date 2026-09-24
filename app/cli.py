"""
`habeny`: administration commands. Installed as /usr/local/bin/habeny, which runs this
as the service user with the service's settings.

  habeny version
  habeny config [check|example|docs]
  habeny db status|migrate|backup|restore FILE|downgrade --to N
  habeny backup create|list|verify FILE|restore FILE
  habeny prune [--dry-run]
  habeny token create USER NAME [--role R] [--expires-days N]|list|revoke ID
  habeny tls fingerprint
  habeny license request|status|install FILE
  habeny audit verify|export [--format csv|jsonl] [--since D] [--until D] [--user U] [--action A]
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


def cmd_backup(args) -> int:
    from app.services import backup
    if args.action == "create":
        print(backup.create_backup("manual"))
        return 0
    if args.action == "list":
        items = backup.list_backups()
        print(f"Backups in {backup.backup_dir()} (scheduled every {config.get('HABENY_BACKUP_INTERVAL_HOURS')} h, "
              f"newest {config.get('HABENY_BACKUP_KEEP')} kept):")
        for item in items:
            print(f"  {item['name']}  {item['size_bytes'] / 1e6:8.1f} MB")
        if not items:
            print("  none yet")
        return 0
    if args.action == "verify":
        m = backup.verify_backup(Path(args.file))
        print(f"OK: Habeny {m['habeny_version']}, schema v{m['schema_version']}, taken {m['created_at']} on "
              f"{m['host']}, {len(m['files'])} files; encryption key: {m['secret_key']}")
        return 0
    # restore replaces data the running app is using
    if _service_active() and not args.force:
        print("error: Habeny is running. Stop it first (sudo systemctl stop habeny), or pass --force.",
              file=sys.stderr)
        return 1
    m = backup.restore_backup(Path(args.file))
    print(f"Restored the backup from {m['created_at']} (Habeny {m['habeny_version']}). The data it replaced is "
          f"kept alongside (*.before-restore, and the database under backups/).")
    if m.get("config_restored_to"):
        print(f"Its settings are in {m['config_restored_to']}; compare with /etc/habeny/habeny.conf and copy over "
              "what you need (as root).")
    return 0


def cmd_prune(args) -> int:
    from app.services.maintenance import prune
    removed = prune(dry_run=args.dry_run)
    if args.dry_run:
        print(f"Would delete {removed['audit_entries']} audit entries, {removed['activity_files']} old activity log "
              f"file(s) and {removed['report_files']} report file(s); other database rows past retention are counted "
              "when deleted.")
    else:
        print("Deleted: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in removed.items()))
    return 0


def _service_active() -> bool:
    from app.services.instance import running_pid
    if running_pid() is not None:  # a Habeny holds the data directory (service or not)
        return True
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


def _schema_current() -> None:
    from app import migrations
    from app.config import DB_PATH
    if migrations.current_version(DB_PATH) < migrations.latest_version():
        raise RuntimeError("the database needs migrating first: start Habeny or run `habeny db migrate`")


def cmd_token(args) -> int:
    """API tokens from the command line, e.g. to bootstrap automation on a new server."""
    from datetime import datetime, timedelta, timezone

    from app.config import DB_PATH
    from app.db import create_api_token, delete_api_token, get_user_by_username, list_api_tokens
    from app.services.activity import log_activity
    from app.services.auth import has_role, new_api_token, token_hash

    _schema_current()
    if args.action == "create":
        user = get_user_by_username(DB_PATH, args.user)
        if not user:
            print(f"error: no user {args.user!r}", file=sys.stderr)
            return 1
        role = args.role or user["role"]
        if not has_role(user, role):
            print(f"error: {user['username']} is a {user['role']}; the token can't have the {role} role", file=sys.stderr)
            return 1
        expires = ((datetime.now(timezone.utc) + timedelta(days=args.expires_days)).isoformat()
                   if args.expires_days else None)
        token, prefix = new_api_token()
        create_api_token(DB_PATH, user["id"], args.name, token_hash(token), prefix, role, expires)
        log_activity("api_token_created", {"username": user["username"], "token": args.name, "role": role,
                                           "expires_at": expires, "via": "cli"}, user="cli")
        print(token)
        print(f"# {role} token '{args.name}' for {user['username']}, "
              f"{'expires ' + expires[:10] if expires else 'never expires'}. It isn't stored: copy it now.",
              file=sys.stderr)
        return 0
    if args.action == "list":
        rows = list_api_tokens(DB_PATH)
        if not rows:
            print("No API tokens")
        for row in rows:
            print(f"{row['id']:>4}  {row['prefix']}…  {row['username']:<16} {row['name']:<24} {row['role']:<8} "
                  f"expires {(row['expires_at'] or 'never')[:10]:<10}  last used {(row['last_used_at'] or 'never')[:16]}")
        return 0
    if args.action == "revoke":
        deleted = delete_api_token(DB_PATH, args.id)
        if not deleted:
            print(f"error: no token {args.id}", file=sys.stderr)
            return 1
        log_activity("api_token_revoked", {"username": deleted["username"], "token": deleted["name"], "via": "cli"},
                     user="cli")
        print(f"Revoked '{deleted['name']}' of {deleted['username']}")
        return 0
    return 2


def cmd_tls(args) -> int:
    from app.tls import certificate_fingerprint, tls_mode
    if tls_mode() == "off":
        print("TLS is off here (HABENY_TLS=off): the reverse proxy in front has the certificate", file=sys.stderr)
        return 1
    fingerprint = certificate_fingerprint()
    if not fingerprint:
        print("No certificate yet: it's created when Habeny first starts", file=sys.stderr)
        return 1
    print(fingerprint)
    return 0


def cmd_audit(args) -> int:
    from app.services import audit

    _schema_current()
    if args.action == "verify":
        result = audit.verify()
        if result["ok"]:
            print(f"OK: {result['checked']} entries verified (ids {result['anchor_id'] + 1}–{result['last_id']}), "
                  f"head {result['head_hash']}")
            return 0
        print(f"BROKEN at entry {result['problem']['id']}: {result['problem']['reason']} "
              f"({result['checked']} entries before it are intact)", file=sys.stderr)
        return 1
    if args.action == "export":
        filters = audit.Filters(action=args.action_filter, user=args.user, since=args.since, until=args.until)
        for chunk in audit.export(filters, args.format):
            sys.stdout.write(chunk)
        return 0
    return 2


def cmd_license(args) -> int:
    import socket

    from app.services import licensing
    from app.services.activity import log_activity
    from app.version import __version__
    if args.action == "request":
        print("Send this to your Habeny vendor to get a license for this server:\n")
        print(f"  Server ID:  {licensing.server_id()}")
        print(f"  Host name:  {socket.gethostname()}")
        print(f"  Version:    Habeny {__version__}")
        return 0
    if args.action == "install":
        _schema_current()
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        payload = licensing.install(text)
        log_activity("license_installed", {"license": payload["id"], "customer": payload["customer"],
                                           "expires": payload.get("expires"),
                                           "max_containers": payload.get("max_containers")}, user="cli")
        print(f"Installed license {payload['id']} for {payload['customer']}.")
    info = licensing.status_info()
    print(f"State:      {info['state']}")
    print(f"Server ID:  {info['server_id']}")
    if info["license"]:
        lic = info["license"]
        print(f"License:    {lic['id']} for {lic['customer']} (issued {lic['issued']})")
        print(f"Expires:    {lic['expires'] or 'never'}")
        print(f"Containers: {lic['max_containers'] or 'no limit'}")
    print(info["message"])
    return 0 if info["allows_new_work"] else 1


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

    p_backup = sub.add_parser("backup", help="full backups of Habeny's data")
    backup_sub = p_backup.add_subparsers(dest="action", required=True)
    backup_sub.add_parser("create", help="take a full backup now")
    backup_sub.add_parser("list", help="list full backups")
    p_verify = backup_sub.add_parser("verify", help="check a backup file is complete and undamaged")
    p_verify.add_argument("file")
    p_brestore = backup_sub.add_parser("restore", help="restore data from a backup (stop Habeny first)")
    p_brestore.add_argument("file")
    p_brestore.add_argument("--force", action="store_true", help="even if the service is running")

    p_prune = sub.add_parser("prune", help="delete data past its retention now (runs hourly anyway)")
    p_prune.add_argument("--dry-run", action="store_true", help="only count old files")

    p_token = sub.add_parser("token", help="API tokens for scripts and CI")
    token_sub = p_token.add_subparsers(dest="action", required=True)
    p_tcreate = token_sub.add_parser("create", help="create a token (printed once)")
    p_tcreate.add_argument("user")
    p_tcreate.add_argument("name")
    p_tcreate.add_argument("--role", choices=["viewer", "operator", "admin"], help="default: the user's role")
    p_tcreate.add_argument("--expires-days", type=int, default=90, help="0: never (default 90)")
    token_sub.add_parser("list", help="every user's tokens")
    p_trevoke = token_sub.add_parser("revoke", help="revoke a token by its ID")
    p_trevoke.add_argument("id", type=int)

    p_audit = sub.add_parser("audit", help="the audit trail: verify its hash chain, export it")
    audit_sub = p_audit.add_subparsers(dest="action", required=True)
    audit_sub.add_parser("verify", help="check no entry was changed, removed or reordered")
    p_aexport = audit_sub.add_parser("export", help="write entries (oldest first) to stdout")
    p_aexport.add_argument("--format", choices=["csv", "jsonl"], default="jsonl")
    p_aexport.add_argument("--since", help="ISO date or date-time")
    p_aexport.add_argument("--until", help="ISO date or date-time")
    p_aexport.add_argument("--user")
    p_aexport.add_argument("--action", dest="action_filter", help="exact, or a prefix ending in *")

    p_tls = sub.add_parser("tls", help="this server's certificate")
    p_tls.add_argument("action", choices=["fingerprint"], help="SHA-256 fingerprint, to confirm when adding "
                       "this server as a host in another console")

    p_license = sub.add_parser("license", help="this server's license")
    license_sub = p_license.add_subparsers(dest="action", required=True)
    license_sub.add_parser("request", help="print what the vendor needs to issue a license (the server ID)")
    license_sub.add_parser("status", help="the license and its state (exit status 1: new work is refused)")
    p_linstall = license_sub.add_parser("install", help="install a license file (- reads standard input)")
    p_linstall.add_argument("file")

    args = parser.parse_args(argv)
    handlers = {"version": cmd_version, "config": cmd_config, "db": cmd_db, "backup": cmd_backup,
                "prune": cmd_prune, "token": cmd_token, "audit": cmd_audit, "tls": cmd_tls,
                "license": cmd_license}
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
