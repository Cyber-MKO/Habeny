"""
HTTP route registration — one module per domain, each exposing an APIRouter.
"""
from fastapi import Depends, FastAPI


def register_routes(app: FastAPI) -> None:
    """Include every router. Called by create_app().

    Order matters where paths overlap: e.g. POST /agents/bulk/{operation} must be
    registered before POST /agents/{agent_id}/start, and the SPA catch-all last.

    Everything except /auth/* and the static frontend requires a signed-in session
    (HTTP routes and WebSockets alike) and the role the request needs (viewer for
    reads, operator for changes and the console; see app.services.auth.require_access).
    """
    from app.routes import (
        activity,
        agents,
        auth,
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
        users,
    )
    from app.services.auth import require_access, require_user

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
        app.include_router(module.router, dependencies=[Depends(require_access)])
    # Account self-service (password, sessions, 2FA) for every role; admin routes check themselves
    app.include_router(users.router, dependencies=[Depends(require_user)])
    app.include_router(auth.router)
    static.register(app)
