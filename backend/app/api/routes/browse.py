"""File browsing endpoints for navigating storage backends."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import store_label
from app.api.routes.labels import summarize
from app.models.schemas import LabelUploadResponse
from app.services.label_parser import parse_label
from app.services.storage import StorageBackend, get_backend, list_backends

router = APIRouter()


def _backend(source: str) -> StorageBackend:
    backend = get_backend(source) if not source.startswith("_") else None
    if not backend:
        raise HTTPException(status_code=404, detail=f"Storage source '{source}' not found")
    return backend


@router.get("/sources")
def get_sources() -> list[dict[str, str]]:
    """List all configured storage backends."""
    return list_backends()


@router.get("/list")
def browse_directory(
    source: str = Query(default="local", description="Storage backend name"),
    path: str = Query(default="", description="Directory path to browse"),
) -> dict[str, Any]:
    """List files and directories at the given path."""
    backend = _backend(source)
    target_path = path or backend.root

    try:
        entries = backend.list_directory(target_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {
        "source": source,
        "current_path": target_path,
        "parent_path": backend.get_parent(target_path),
        "entries": [
            {"name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size, "is_label": e.is_label}
            for e in entries
        ],
    }


@router.post("/open")
def open_label(
    source: str = Query(default="local", description="Storage backend name"),
    path: str = Query(description="Path to the label file"),
) -> LabelUploadResponse:
    """Open a label from a storage backend.

    Only the label itself is read here. Data files are read later, in place, with
    ranged reads — nothing is downloaded or copied, for local disk and S3 alike.
    """
    backend = _backend(source)
    if not backend.file_exists(path):
        raise HTTPException(status_code=404, detail=f"Label file not found: {path}")

    try:
        parsed = parse_label(path, content=backend.read_file(path), source=source)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse label: {e}")

    label_id = store_label(parsed)
    return LabelUploadResponse(label_id=label_id, filename=parsed["filename"], structures=summarize(parsed))
