"""
Teams (admins): who sees which containers, container limits, moving containers between teams.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import DB_PATH
from app.core.lxc_backend import lxc
from app.db import get_user_by_id
from app.models import APIResponse
from app.services import tenancy
from app.services.activity import log_activity
from app.services.auth import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


class TeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[\w .-]+$")
    description: str | None = Field(None, max_length=300)
    max_containers: int | None = Field(None, ge=0, le=100000)  # None: no limit


class UserTeamRequest(BaseModel):
    team_id: int | None = None
    max_containers: int | None = Field(None, ge=0, le=100000)


class AssignRequest(BaseModel):
    team_id: int | None = None  # None: no team
    containers: list[str] = Field(..., min_length=1, max_length=5000)


def _existing() -> list[str]:
    return list(lxc.list_containers())


@router.get("/teams", response_model=APIResponse)
async def list_teams():
    teams = await asyncio.to_thread(tenancy.list_teams)
    usage = await asyncio.to_thread(lambda: tenancy.usage(_existing()))
    for team in teams:
        team["containers"] = usage["teams"].get(team["id"], 0)
    return APIResponse(success=True, message=f"{len(teams)} teams", data={"teams": teams, "user_usage": usage["users"]})


@router.post("/teams", response_model=APIResponse)
async def create_team(body: TeamRequest):
    team = await asyncio.to_thread(tenancy.create_team, body.name.strip(), body.description, body.max_containers)
    if team is None:
        raise HTTPException(status_code=409, detail=f"A team named '{body.name}' exists")
    log_activity("team_created", {"team": team["name"], "max_containers": team["max_containers"]})
    return APIResponse(success=True, message=f"Team '{team['name']}' created", data={"team": team})


@router.put("/teams/{team_id}", response_model=APIResponse)
async def update_team(team_id: int, body: TeamRequest):
    team = await asyncio.to_thread(tenancy.update_team, team_id, body.name.strip(), body.description,
                                   body.max_containers)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    log_activity("team_updated", {"team": team["name"], "max_containers": team["max_containers"]})
    return APIResponse(success=True, message=f"Team '{team['name']}' saved", data={"team": team})


@router.delete("/teams/{team_id}", response_model=APIResponse)
async def delete_team(team_id: int):
    """Its members and containers go back to having no team."""
    team = await asyncio.to_thread(tenancy.delete_team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    log_activity("team_deleted", {"team": team["name"]})
    return APIResponse(success=True, message=f"Team '{team['name']}' deleted; its members and containers have no team now")


@router.put("/users/{user_id}/team", response_model=APIResponse)
async def set_user_team(user_id: int, body: UserTeamRequest):
    target = get_user_by_id(DB_PATH, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    team = tenancy.get_team(body.team_id) if body.team_id is not None else None
    if body.team_id is not None and team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    await asyncio.to_thread(tenancy.set_user_team, user_id, body.team_id, body.max_containers)
    log_activity("user_team_changed", {"username": target["username"], "team": team["name"] if team else None,
                                       "max_containers": body.max_containers})
    return APIResponse(success=True, message=f"{target['username']}: "
                       f"{'team ' + team['name'] if team else 'no team'}, "
                       f"{'limit ' + str(body.max_containers) if body.max_containers is not None else 'no limit'}")


@router.post("/teams/assign", response_model=APIResponse)
async def assign_containers(body: AssignRequest):
    """Move existing containers to a team (or to no team)."""
    team = tenancy.get_team(body.team_id) if body.team_id is not None else None
    if body.team_id is not None and team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    existing = set(await asyncio.to_thread(_existing))
    names = [n for n in body.containers if n in existing]
    missing = [n for n in body.containers if n not in existing]
    await asyncio.to_thread(tenancy.assign, names, body.team_id)
    log_activity("containers_assigned_to_team", {"team": team["name"] if team else None, "containers": names[:200],
                                                 "count": len(names)})
    return APIResponse(success=True, message=f"Moved {len(names)} container(s) to {team['name'] if team else 'no team'}",
                       data={"assigned": names, "not_found": missing})
