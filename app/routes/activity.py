"""
The audit trail (activity log): search, export and verify.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models import APIResponse
from app.services import audit
from app.services.auth import require_admin

router = APIRouter()


def _date(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be an ISO date or date-time") from None
    return value


def _filters(action: str | None = Query(None, max_length=100, description="Exact action, or a prefix ending in *"),
             user: str | None = Query(None, max_length=64),
             status: str | None = Query(None, max_length=20),
             since: str | None = Query(None, description="ISO date or date-time (inclusive)"),
             until: str | None = Query(None, description="ISO date (whole day) or date-time (inclusive)"),
             q: str | None = Query(None, max_length=200, description="Text in the action or details")) -> audit.Filters:
    return audit.Filters(action=action or None, user=user or None, status=status or None,
                         since=_date(since, "since"), until=_date(until, "until"), q=q or None)


@router.get("/activity/logs", response_model=APIResponse)
async def get_activity_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    filters: audit.Filters = Depends(_filters),
):
    """Newest-first page of the audit trail, filtered by action, user, status, dates or text."""
    logs, total = await asyncio.to_thread(audit.query, filters, offset, limit)
    return APIResponse(success=True, message=f"Retrieved {len(logs)} activity logs", data={
        "logs": logs, "total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total,
    })


@router.get("/activity/facets", response_model=APIResponse)
async def get_activity_facets():
    """The actions and users in the trail, for filter menus."""
    return APIResponse(success=True, message="Activity facets", data=await asyncio.to_thread(audit.facets))


@router.get("/activity/export")
async def export_activity(fmt: str = Query("csv", alias="format", pattern="^(csv|jsonl)$"),
                          filters: audit.Filters = Depends(_filters)):
    """Download matching entries (oldest first) as CSV or JSON Lines, with their hashes."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    media = "text/csv" if fmt == "csv" else "application/x-ndjson"
    return StreamingResponse(
        audit.export(filters, fmt), media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="habeny-audit-{stamp}.{fmt}"'},
    )


@router.get("/activity/verify", response_model=APIResponse)
async def verify_activity(admin: dict = Depends(require_admin)):
    """Recompute the hash chain: shows whether any entry was changed, removed or reordered."""
    result = await asyncio.to_thread(audit.verify)
    message = (f"Audit trail intact: {result['checked']} entries verified" if result["ok"]
               else f"Audit trail broken at entry {result['problem']['id']}: {result['problem']['reason']}")
    return APIResponse(success=result["ok"], message=message, data=result)
