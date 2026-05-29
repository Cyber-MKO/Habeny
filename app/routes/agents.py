"""
Agent/container endpoints: deploy, list, get, start, stop, delete, bulk ops.

Will receive from main.py (Phase 4):
  - POST /agents/deploy
  - GET  /agents
  - GET  /agents/stats
  - GET  /agents/{agent_id}
  - POST /agents/{agent_id}/start
  - POST /agents/{agent_id}/stop
  - DELETE /agents/{agent_id}
  - POST /agents/bulk/{operation}
"""
from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["agents"])

# Phase 4: move deploy_agents(), list_agents(), etc. here
