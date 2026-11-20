import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.deps import label_store
from app.api.routes import browse, images, labels, tables
from app.services.label_store import CLEANUP_INTERVAL_SECONDS
from app.services.storage import init_default_backends

logger = logging.getLogger(__name__)


async def _periodic_cleanup() -> None:
    """Remove expired labels/uploads on a fixed schedule, even when no new uploads arrive."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(label_store.cleanup)
        except Exception:  # keep the loop alive; the next run will retry
            logger.exception("Periodic label cleanup failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    label_store.cleanup()  # purge records/uploads that expired while the server was down
    task = asyncio.create_task(_periodic_cleanup())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
    title="PDS4 Viewer API",
    description="API for viewing and exploring NASA PDS4 data products",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("PDS_CORS_ORIGINS", "http://localhost:5173").split(",") if o],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(labels.router, prefix="/api/labels", tags=["labels"])
app.include_router(tables.router, prefix="/api/tables", tags=["tables"])
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(browse.router, prefix="/api/browse", tags=["browse"])

init_default_backends(config.UPLOAD_DIR)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def client_config() -> dict[str, object]:
    """Features the frontend should show for this deployment."""
    return {"upload_enabled": config.UPLOAD_ENABLED, "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024)}


# Optionally serve the built frontend from the same origin (single-container deploys).
# Mounted last so /api routes take precedence.
_static_dir = os.environ.get("PDS_STATIC_DIR")
if _static_dir and Path(_static_dir).is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
