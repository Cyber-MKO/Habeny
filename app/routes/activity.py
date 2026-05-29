"""
Activity log endpoints.

Will receive from main.py (Phase 4):
  - GET /activity/logs
"""
from fastapi import APIRouter

router = APIRouter(prefix="/activity", tags=["activity"])

# Phase 4: move get_activity_logs() here
