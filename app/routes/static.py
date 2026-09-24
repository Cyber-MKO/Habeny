"""
Serves the built React SPA. Registered last: its catch-all route must not shadow the API.
"""
from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse

from app.config import ROOT_DIR, STATIC_DIR


def register(app: FastAPI) -> None:
    @app.get("/THIRD_PARTY_NOTICES.txt", include_in_schema=False)
    async def third_party_notices():
        """Open-source licenses of the bundled packages (written by release builds)."""
        for path in (STATIC_DIR / "THIRD_PARTY_NOTICES.txt", ROOT_DIR / "THIRD_PARTY_NOTICES.txt"):
            if path.is_file():
                return FileResponse(path, media_type="text/plain; charset=utf-8")
        return PlainTextResponse("This install wasn't built from a release, so it has no THIRD_PARTY_NOTICES.txt. "
                                 "Generate it with: python3 deploy/third_party_notices.py\n", status_code=404)

    if not STATIC_DIR.is_dir():
        return

    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse as StarletteFileResponse

    # Serve built assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the React SPA; fall back to index.html for client-side routing."""
        file = (STATIC_DIR / path).resolve()
        # Never serve anything outside the build directory (e.g. /..%2f..%2fetc/shadow)
        if file.is_relative_to(STATIC_DIR.resolve()) and file.is_file():
            return StarletteFileResponse(str(file))
        return StarletteFileResponse(str(STATIC_DIR / "index.html"))
