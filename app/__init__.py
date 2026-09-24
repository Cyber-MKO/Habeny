"""
Multi-SIEM Container Emulation Platform — application package.
"""
import logging

logger = logging.getLogger(__name__)


def _initialize_storage() -> None:
    """Create data directories, initialize the database and recover leftover state."""
    from app.config import AGENTS_DIR, CONFIGS_DIR, DATA_DIR, DB_PATH, LOGS_DIR, REPORTS_DIR
    from app.db import init_db
    from app.services.agent_info import migrate_legacy_agent_metadata

    for dir_path in [DATA_DIR, CONFIGS_DIR, REPORTS_DIR, LOGS_DIR, AGENTS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    init_db(DB_PATH)

    # Clean up benchmarks left in "running" state from a previous crash/restart
    try:
        from app.services.benchmarks import cleanup_stale_benchmarks
        cleaned = cleanup_stale_benchmarks()
        if cleaned:
            logger.info(f"Recovered {cleaned} stale benchmark(s) from previous session")
    except Exception as e:
        logger.warning(f"Benchmark cleanup failed: {e}")

    migrate_legacy_agent_metadata()

    from app.services.lifecycle import recover_interrupted_deployments
    recover_interrupted_deployments()

    # Jobs and schedules from before the restart (running ones become "interrupted")
    from app.state import import_legacy_config_templates, load_persisted_state
    load_persisted_state(DB_PATH)
    import_legacy_config_templates(CONFIGS_DIR)

    from app.services.setup_token import ensure_setup_token
    ensure_setup_token()

    # Secrets stored before encryption existed
    from app.db import encrypt_plaintext_manager_secrets
    from app.services.benchmarks import scrub_stored_benchmark_secrets
    encrypted = encrypt_plaintext_manager_secrets(DB_PATH)
    scrubbed = scrub_stored_benchmark_secrets()
    if encrypted or scrubbed:
        logger.info(f"Secured stored secrets: {encrypted} manager profile key(s) encrypted, "
                    f"{scrubbed} benchmark config(s) scrubbed")


def create_app():
    """Application factory. Initializes storage, middleware and all routes."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.config import CORS_ORIGINS, DEPLOY_WORKERS, check
    from app.version import __version__
    from app.middleware import RequestContextMiddleware, StripApiPrefixMiddleware
    from app.routes import register_routes

    check()  # stop with every configuration problem listed, before touching anything
    from app.services import instance
    instance.acquire()  # one Habeny per data directory
    _initialize_storage()
    from app.services import oidc
    if oidc.settings():  # fails fast on incomplete single sign-on settings
        logger.info("Single sign-on (OIDC) enabled with issuer %s", oidc.settings().issuer)

    app = FastAPI(
        title="Multi-SIEM Container Emulation Platform",
        description="LXC-based platform for deploying containers that run SIEM agents at scale",
        version=__version__,
    )
    logger.info(f"Initialized; up to {DEPLOY_WORKERS} containers deploy in parallel")

    # The UI is served from this origin (and the dev server proxies), so browsers need no
    # cross-origin access. Only origins listed in HABENY_CORS_ORIGINS get it.
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(StripApiPrefixMiddleware)
    app.add_middleware(RequestContextMiddleware)  # added last = outermost: sees every request

    register_routes(app)

    from app.services import lifecycle
    from app.services.logs import interrupt_for_shutdown
    from app.services.maintenance import maintenance
    from app.state import interrupt_running_simulations
    lifecycle.on_shutdown(interrupt_running_simulations)
    lifecycle.on_shutdown(interrupt_for_shutdown)

    @app.on_event("startup")
    async def startup_event():
        maintenance.start()  # background housekeeping: see app/services/maintenance.py
        from app.services.logs import resume_log_schedules
        resume_log_schedules()

    @app.on_event("shutdown")
    async def shutdown_event():
        maintenance.stop()
        logger.info("Shutdown complete")

    return app
