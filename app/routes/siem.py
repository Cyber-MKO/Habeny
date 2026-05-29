"""
SIEM-specific stat endpoints.

Will receive from main.py (Phase 4):
  - GET /siem/{siem_type}/stats
"""
from fastapi import APIRouter

router = APIRouter(prefix="/siem", tags=["siem"])

# Phase 4: move get_siem_stats() here
