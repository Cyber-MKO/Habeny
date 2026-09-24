"""
Runs the app under uvicorn with a graceful shutdown (see app/services/lifecycle.py).
"""
import uvicorn

from app import config
from app.services import lifecycle
from app.tls import listen_address, server_ssl_options


class _Server(uvicorn.Server):
    def handle_exit(self, sig, frame):
        # uvicorn runs the app's shutdown hooks only after open requests finish, and a
        # deployment is an open request: tell running work now so it can wind down
        lifecycle.begin_shutdown()
        super().handle_exit(sig, frame)


def serve(app) -> None:
    host, port = listen_address()
    server = _Server(uvicorn.Config(
        app,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=config.get("HABENY_FORWARDED_ALLOW_IPS"),
        log_level=config.get("HABENY_LOG_LEVEL"),
        # Deployments get SHUTDOWN_TIMEOUT to finish; allow a little more for their responses
        timeout_graceful_shutdown=config.SHUTDOWN_TIMEOUT + 15,
        **server_ssl_options(),
    ))
    server.run()
