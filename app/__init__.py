"""
Multi-SIEM Container Emulation Platform — application package.
"""
import logging
from multiprocessing import cpu_count

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

    from app.config import CORS_ORIGINS, MAX_WORKERS
    from app.middleware import StripApiPrefixMiddleware, track_request_latency
    from app.routes import register_routes

    _initialize_storage()
    from app.services import oidc
    if oidc.settings():  # fails fast on incomplete single sign-on settings
        logger.info("Single sign-on (OIDC) enabled with issuer %s", oidc.settings().issuer)

    app = FastAPI(
        title="Multi-SIEM Container Emulation Platform",
        description="LXC-based platform for deploying containers that run SIEM agents at scale",
        version="2.0.0",
    )
    logger.info(f"Initialized with {MAX_WORKERS} max thread workers and {cpu_count()} CPU cores")

    # The UI is served from this origin (and the dev server proxies), so browsers need no
    # cross-origin access. Only origins listed in HABENY_CORS_ORIGINS get it.
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type"],
        )
    app.add_middleware(StripApiPrefixMiddleware)
    app.middleware("http")(track_request_latency)

    register_routes(app)

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutdown complete")

    return app
