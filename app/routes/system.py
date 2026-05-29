"""
System endpoints: root, info, health.

Will receive from main.py (Phase 4):
  - GET  /
  - GET  /system/info
  - GET  /system/health
"""
from fastapi import APIRouter

router = APIRouter(tags=["system"])

# Phase 4: move root(), system_info(), health_check() here
