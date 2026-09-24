"""
Entry point: python3 main.py (or uvicorn main:app). The application lives in app/.
Settings: see app/config.py, or run `habeny config`.
"""
import sys

EX_CONFIG = 78  # the systemd unit doesn't restart on this

try:
    from app import config
    from app.logging_config import configure_from_settings
    configure_from_settings()
except (ValueError, OSError) as e:  # unreadable config file, invalid setting, unwritable log file
    print(f"habeny: {e}", file=sys.stderr)
    sys.exit(EX_CONFIG)

from app import create_app  # noqa: E402  (logging must be configured first)

from app.services.instance import AlreadyRunning  # noqa: E402

try:
    app = create_app()
except (config.ConfigError, AlreadyRunning) as e:
    print(f"habeny: {e}", file=sys.stderr)
    sys.exit(EX_CONFIG)

if __name__ == "__main__":
    from app.server import serve

    serve(app)
