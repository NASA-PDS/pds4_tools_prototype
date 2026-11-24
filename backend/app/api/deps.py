"""Shared state and FastAPI dependencies for API routes."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException

from app import config
from app.services.label_store import LabelStore

label_store = LabelStore(config.LABEL_DIR, config.UPLOAD_DIR, config.CACHE_TTL_SECONDS)


def store_label(parsed_label: dict[str, Any]) -> str:
    """Store a parsed label and return its ID."""
    return label_store.put(parsed_label)


def get_label(label_id: str) -> dict[str, Any] | None:
    """Retrieve a stored label by ID."""
    return label_store.get(label_id)


def list_labels() -> list[dict[str, str]]:
    """List all stored labels."""
    return label_store.list()


def clear_labels() -> None:
    """Clear all stored labels."""
    label_store.clear()


# ---------------------------------------------------------------------------
# Dependencies that resolve (label_id, structure_index) path params
# ---------------------------------------------------------------------------

def require_label(label_id: str) -> dict[str, Any]:
    label = get_label(label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    return label


def _structure(label: dict[str, Any], structure_index: int, kind: str) -> dict[str, Any]:
    structures = label.get("structures", [])
    if structure_index < 0 or structure_index >= len(structures):
        raise HTTPException(status_code=404, detail="Structure not found")
    s = structures[structure_index]
    if kind not in s.get("structure_type", ""):
        noun = "a table" if kind == "Table" else "an array/image"
        raise HTTPException(status_code=400, detail=f"Structure is not {noun}")
    return s


def table_structure(structure_index: int, label: Annotated[dict, Depends(require_label)]) -> dict[str, Any]:
    return _structure(label, structure_index, "Table")


def array_structure(structure_index: int, label: Annotated[dict, Depends(require_label)]) -> dict[str, Any]:
    return _structure(label, structure_index, "Array")


Label = Annotated[dict[str, Any], Depends(require_label)]
TableStructure = Annotated[dict[str, Any], Depends(table_structure)]
ArrayStructure = Annotated[dict[str, Any], Depends(array_structure)]
