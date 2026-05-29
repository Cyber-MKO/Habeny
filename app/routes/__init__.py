"""
HTTP route registration — one module per domain, each exposing an APIRouter.
"""
from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Import and include every router.  Called by create_app()."""
    from app.routes import (
        system,
        agents,
        groups,
        simulations,
        configs,
        reports,
        logs,
        activity,
        siem,
        console,
    )

    app.include_router(system.router)
    app.include_router(agents.router)
    app.include_router(groups.router)
    app.include_router(simulations.router)
    app.include_router(configs.router)
    app.include_router(reports.router)
    app.include_router(logs.router)
    app.include_router(activity.router)
    app.include_router(siem.router)
    # console uses @app.websocket directly — registered separately
    console.register(app)
