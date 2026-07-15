"""FastAPI app factory for the kicad-agent playground.

Creates the FastAPI application with static file serving,
API router mounting, and WebSocket support.
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from volta.playground.api import router as api_router
from volta.playground.ws import router as ws_router

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    upload_dir: Path | None = None,
    max_upload_mb: int = 10,
) -> FastAPI:
    """Create and configure the playground FastAPI application.

    Args:
        upload_dir: Directory for uploaded files. Defaults to tempdir.
        max_upload_mb: Maximum upload file size in MB.

    Returns:
        Configured FastAPI app with API routes and static files.
    """
    app = FastAPI(
        title="kicad-agent Playground",
        description="Interactive web UI for exploring KiCad operations",
        version="0.1.0",
    )

    # Store config in app state
    if upload_dir is None:
        upload_dir = Path(tempfile.mkdtemp(prefix="kicad-playground-"))
        _upload_dir_for_cleanup = upload_dir

        def _cleanup_upload_dir() -> None:
            try:
                shutil.rmtree(_upload_dir_for_cleanup, ignore_errors=True)
            except Exception:
                pass

        atexit.register(_cleanup_upload_dir)

    app.state.upload_dir = upload_dir
    app.state.max_upload_bytes = max_upload_mb * 1024 * 1024
    app.state.sessions: dict[str, dict] = {}

    # Mount API routes
    app.include_router(api_router, prefix="/api")

    # Mount WebSocket
    app.include_router(ws_router)

    # Serve static frontend
    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app
