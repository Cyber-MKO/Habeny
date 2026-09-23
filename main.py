"""
Entry point: python3 main.py (or uvicorn main:app). The application lives in app/.
Settings: see app/config.py, or run `habeny config`.
"""
import logging
import sys

EX_CONFIG = 78  # the systemd unit doesn't restart on this

try:
    from app import config
except ValueError as e:  # an unreadable config file or an invalid setting used at import
    print(f"habeny: {e}", file=sys.stderr)
    sys.exit(EX_CONFIG)

logging.basicConfig(
    level=config.get("HABENY_LOG_LEVEL").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from app import create_app  # noqa: E402  (logging must be configured first)

try:
    app = create_app()
except config.ConfigError as e:
    print(f"habeny: {e}", file=sys.stderr)
    sys.exit(EX_CONFIG)

if __name__ == "__main__":
    from app.server import serve

    serve(app)
