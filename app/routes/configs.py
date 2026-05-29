"""
Configuration template endpoints.

Will receive from main.py (Phase 4):
  - GET  /configs
  - POST /configs/import
  - GET  /configs/export/{template_id}
"""
from fastapi import APIRouter

router = APIRouter(prefix="/configs", tags=["configs"])

# Phase 4: move config endpoints here
