"""
HTTP route registration — one module per domain, each exposing an APIRouter.
"""
from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Include every router. Called by create_app().

    Order matters where paths overlap: e.g. POST /agents/bulk/{operation} must be
    registered before POST /agents/{agent_id}/start, and the SPA catch-all last.
    """
    from app.routes import (
        activity,
        agents,
        benchmarks,
        configs,
        console,
        groups,
        logs,
        managers,
        metrics,
        reports,
        siem,
        simulations,
        static,
        syslog_configs,
        system,
    )

    for module in (
        system,
        metrics,
        console,
        agents,
        logs,
        groups,
        simulations,
        configs,
        reports,
        activity,
        managers,
        benchmarks,
        syslog_configs,
        siem,
    ):
        app.include_router(module.router)
    static.register(app)
