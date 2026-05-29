"""
WebSocket console session.

Will receive from main.py (Phase 4):
  - WS /ws/console/{container_name}
  - resize_pty helper

Uses app.websocket directly (not APIRouter) because FastAPI
requires websocket routes to be registered on the app instance.
"""
from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """Register the WebSocket console route on the app."""
    pass  # Phase 4: move console_session() here
