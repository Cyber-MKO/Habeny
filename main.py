"""
Entry point: python3 main.py (or uvicorn main:app). The application lives in app/.
"""
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from app import create_app  # noqa: E402  (logging must be configured first)

app = create_app()

if __name__ == "__main__":
    import uvicorn

    from app.tls import listen_address, server_ssl_options

    host, port = listen_address()
    uvicorn.run(app, host=host, port=port, proxy_headers=True, **server_ssl_options())
