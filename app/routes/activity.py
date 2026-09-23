"""
Activity log retrieval.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Query

from app.models import APIResponse
from app.services.activity import read_activity_page

router = APIRouter()


@router.get("/activity/logs", response_model=APIResponse)
async def get_activity_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="Filter by action type")
):
    """Retrieve activity logs with filtering"""
    try:
        paginated_logs, total = await asyncio.to_thread(read_activity_page, action, offset, limit)

        return APIResponse(
            success=True,
            message=f"Retrieved {len(paginated_logs)} activity logs",
            data={
                "logs": paginated_logs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        )

    except Exception as e:
        return APIResponse(success=False, message="Failed to retrieve activity logs", error=str(e))
