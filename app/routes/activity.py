"""
Activity log retrieval.
"""
from typing import Optional

from fastapi import APIRouter, Query

from app.models import APIResponse
from app.services.activity import read_activity_logs_from_files

router = APIRouter()


@router.get("/activity/logs", response_model=APIResponse)
async def get_activity_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="Filter by action type")
):
    """Retrieve activity logs with filtering"""
    try:
        filtered_logs = read_activity_logs_from_files(action)
        total = len(filtered_logs)
        paginated_logs = filtered_logs[offset:offset + limit]

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
