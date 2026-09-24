"""
Teams and container limits (multi-tenancy).

- Every container Habeny creates records the team and user that created it.
- Admins see and manage every container. Anyone else sees only their team's containers;
  users without a team see only containers that belong to no team (so an install that
  never creates teams works exactly as before).
- Limits: a team's max_containers caps its containers in total, a user's max_containers
  caps the ones they created. Checked before deploying and before benchmarks.

Configuration shared by everyone (manager profiles, syslog configs, groups, templates) and
the host-wide dashboard stay visible to all roles that could see them before.
"""
import contextlib
import sqlite3
from typing import Any

from fastapi import HTTPException, status

from app import config
from app.models import utc_now


class QuotaExceeded(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def is_unrestricted(user: dict | None) -> bool:
    return user is None or user.get("role") == "admin"


def owners(names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """name -> {team_id, owner_id} for containers with a recorded owner."""
    with contextlib.closing(_conn()) as conn:
        rows = conn.execute("SELECT name, team_id, owner_id FROM container_owners").fetchall()
    wanted = set(names) if names is not None else None
    return {r["name"]: dict(r) for r in rows if wanted is None or r["name"] in wanted}


def visible(user: dict | None, names: list[str]) -> list[str]:
    """The containers among `names` this user may see, in the same order."""
    if is_unrestricted(user):
        return list(names)
    team = user.get("team_id")
    recorded = owners(names)
    return [n for n in names if (recorded.get(n) or {}).get("team_id") == team]


def same_team(user: dict | None, team_id: int | None) -> bool:
    """For team-stamped records (simulations, reports): admins see all, others their team's."""
    return is_unrestricted(user) or user.get("team_id") == team_id


def stamp(user: dict | None) -> dict[str, Any]:
    """Fields recording who started a job and for which team."""
    return {"team_id": (user or {}).get("team_id"), "started_by": (user or {}).get("username")}


def can_see(user: dict | None, name: str) -> bool:
    return bool(visible(user, [name]))


def record(names: list[str], user: dict | None) -> None:
    """The user (and their team) own these new containers."""
    if not names:
        return
    team_id = (user or {}).get("team_id")
    owner_id = (user or {}).get("id")
    now = utc_now().isoformat()
    with contextlib.closing(_conn()) as conn:
        conn.executemany("INSERT OR REPLACE INTO container_owners (name, team_id, owner_id, created_at)"
                         " VALUES (?, ?, ?, ?)", [(n, team_id, owner_id, now) for n in names])
        conn.commit()


def forget(names: list[str]) -> None:
    with contextlib.closing(_conn()) as conn:
        conn.executemany("DELETE FROM container_owners WHERE name = ?", [(n,) for n in names])
        conn.commit()


def assign(names: list[str], team_id: int | None) -> int:
    """Move containers to a team (or to no team). Returns how many changed."""
    now = utc_now().isoformat()
    with contextlib.closing(_conn()) as conn:
        for name in names:
            conn.execute("INSERT INTO container_owners (name, team_id, owner_id, created_at) VALUES (?, ?, NULL, ?)"
                         " ON CONFLICT(name) DO UPDATE SET team_id = excluded.team_id", (name, team_id, now))
        conn.commit()
    return len(names)


def check_quota(user: dict | None, adding: int, existing: list[str]) -> None:
    """Refuse `adding` more containers when that would pass the user's or their team's limit.
    `existing`: the containers that exist now (stale ownership rows don't count)."""
    if user is None or adding <= 0:
        return
    live = set(existing)
    recorded = owners(list(live))
    full = _load_user(user["id"])
    if full.get("max_containers") is not None:
        mine = sum(1 for o in recorded.values() if o["owner_id"] == user["id"])
        if mine + adding > full["max_containers"]:
            raise QuotaExceeded(f"Your limit is {full['max_containers']} containers; you have {mine} and asked "
                                f"for {adding} more. Delete some, or ask an admin to raise the limit.")
    if full.get("team_id") is not None:
        team = get_team(full["team_id"])
        if team and team.get("max_containers") is not None:
            used = sum(1 for o in recorded.values() if o["team_id"] == team["id"])
            if used + adding > team["max_containers"]:
                raise QuotaExceeded(f"Team {team['name']} is limited to {team['max_containers']} containers; it has "
                                    f"{used} and you asked for {adding} more.")


def usage(existing: list[str]) -> dict[str, dict[int, int]]:
    """Containers per team and per user, counting only containers that exist."""
    recorded = owners(existing)
    by_team: dict[int, int] = {}
    by_user: dict[int, int] = {}
    for o in recorded.values():
        if o["team_id"] is not None:
            by_team[o["team_id"]] = by_team.get(o["team_id"], 0) + 1
        if o["owner_id"] is not None:
            by_user[o["owner_id"]] = by_user.get(o["owner_id"], 0) + 1
    return {"teams": by_team, "users": by_user}


def _load_user(user_id: int) -> dict[str, Any]:
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT id, team_id, max_containers FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else {}


# ── teams ───────────────────────────────────────────────────────────────

def list_teams() -> list[dict[str, Any]]:
    with contextlib.closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM users u WHERE u.team_id = t.id) AS members"
            " FROM teams t ORDER BY t.name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def get_team(team_id: int) -> dict[str, Any] | None:
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
    return dict(row) if row else None


def create_team(name: str, description: str | None, max_containers: int | None) -> dict[str, Any] | None:
    try:
        with contextlib.closing(_conn()) as conn:
            cur = conn.execute("INSERT INTO teams (name, description, max_containers, created_at) VALUES (?, ?, ?, ?)",
                               (name, description, max_containers, utc_now().isoformat()))
            conn.commit()
            return get_team(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def update_team(team_id: int, name: str, description: str | None, max_containers: int | None) -> dict | None:
    try:
        with contextlib.closing(_conn()) as conn:
            cur = conn.execute("UPDATE teams SET name = ?, description = ?, max_containers = ? WHERE id = ?",
                               (name, description, max_containers, team_id))
            conn.commit()
            if not cur.rowcount:
                return None
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"A team named '{name}' exists") from None
    return get_team(team_id)


def delete_team(team_id: int) -> dict[str, Any] | None:
    """Members and containers go back to having no team."""
    team = get_team(team_id)
    if team:
        with contextlib.closing(_conn()) as conn:
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
            conn.commit()
    return team


def set_user_team(user_id: int, team_id: int | None, max_containers: int | None) -> None:
    with contextlib.closing(_conn()) as conn:
        conn.execute("UPDATE users SET team_id = ?, max_containers = ? WHERE id = ?", (team_id, max_containers, user_id))
        conn.commit()
