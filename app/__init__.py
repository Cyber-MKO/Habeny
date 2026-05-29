"""
Multi-SIEM Container Emulation Platform — application package.

After migration is complete, main.py simply calls create_app().
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Application factory.  Registers all routers and startup hooks."""
    from app.config import DATA_DIR, DB_PATH
    from app.routes import register_routes

    _app = FastAPI(
        title="Multi-SIEM Container Emulation Platform",
        description="LXC-based platform for deploying containers that run SIEM agents at scale",
        version="2.0.0",
    )

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    register_routes(_app)
    return _app
