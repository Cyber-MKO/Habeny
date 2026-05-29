"""
Log upload and scheduling endpoints.

Will receive from main.py (Phase 4):
  - POST /agents/{agent_id}/logs/upload
  - POST /agents/{agent_id}/logs/schedule
  - POST /agents/logs/schedules/{schedule_id}/stop
  - GET  /agents/logs/schedules
"""
from fastapi import APIRouter

router = APIRouter(tags=["logs"])

# Phase 4: move log endpoints here
