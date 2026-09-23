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
    uvicorn.run(app, host="0.0.0.0", port=9000)
