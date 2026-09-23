"""
Serves the built React SPA. Registered last: its catch-all route must not shadow the API.
"""
from fastapi import FastAPI

from app.config import STATIC_DIR


def register(app: FastAPI) -> None:
    if not STATIC_DIR.is_dir():
        return

    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse as StarletteFileResponse

    # Serve built assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the React SPA; fall back to index.html for client-side routing."""
        file = STATIC_DIR / path
        if file.is_file():
            return StarletteFileResponse(str(file))
        return StarletteFileResponse(str(STATIC_DIR / "index.html"))
