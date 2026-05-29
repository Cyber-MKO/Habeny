"""
Reporting endpoints.

Will receive from main.py (Phase 4):
  - POST /reports/generate
  - GET  /reports/{report_id}
  - GET  /reports/{report_id}/download
"""
from fastapi import APIRouter

router = APIRouter(prefix="/reports", tags=["reports"])

# Phase 4: move report endpoints here
