"""
Group management endpoints.

Will receive from main.py (Phase 4):
  - GET    /groups
  - POST   /groups
  - POST   /groups/{name}/rename
  - DELETE /groups/{name}
  - POST   /groups/{name}/assign
  - POST   /groups/{name}/remove
  - POST   /groups/{name}/bulk/{operation}
  - POST   /groups/{name}/logs/upload
  - POST   /groups/{name}/logs/schedule
"""
from fastapi import APIRouter

router = APIRouter(prefix="/groups", tags=["groups"])

# Phase 4: move group endpoints here
