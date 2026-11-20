"""Image/array data viewing endpoints."""
from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import ArrayStructure
from app.models.schemas import ImageMetadata, ImageRenderParams
from app.services.data_cache import data_cache
from app.services.image_service import get_image_statistics, render_image
from app.services.label_parser import array_band_count, array_plane_shape, read_array_data

router = APIRouter()


def _plane(label_id: str, structure_index: int, s: dict[str, Any], band: int | None) -> np.ndarray:
    """Decoded 2D plane for (label, structure, band), cached across requests."""
    b = band or 0
    try:
        return data_cache.get_or_load(("array", label_id, structure_index, b), lambda: read_array_data(s, b))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{label_id}/{structure_index}", response_model=ImageMetadata)
def get_image_metadata(label_id: str, structure_index: int, s: ArrayStructure) -> ImageMetadata:
    """Get metadata for a specific array/image structure."""
    height, width = array_plane_shape(s)
    return ImageMetadata(
        label_id=label_id,
        structure_index=structure_index,
        name=s.get("name", "Unknown"),
        structure_type=s["structure_type"],
        dimensions=s.get("dimensions", []),
        axis_names=s.get("axis_names", []),
        element_data_type=s.get("element_data_type") or "unknown",
        width=width,
        height=height,
        bands=array_band_count(s),
        band_axis=s.get("band_axis"),
    )


@router.get("/{label_id}/{structure_index}/statistics")
def get_image_stats(
    label_id: str, structure_index: int, s: ArrayStructure, band: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    """Statistics for one plane (min, max, mean, std, percentiles), ignoring special constants."""
    return get_image_statistics(_plane(label_id, structure_index, s, band))


@router.post("/{label_id}/{structure_index}/render")
def render_image_endpoint(
    label_id: str, structure_index: int, params: ImageRenderParams, s: ArrayStructure,
) -> Response:
    """Render a plane to PNG with the given colormap and stretch."""
    data = _plane(label_id, structure_index, s, params.band)
    try:
        png_bytes = render_image(data, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render image: {e}")
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{label_id}/{structure_index}/pixel")
def get_pixel_value(
    label_id: str,
    structure_index: int,
    s: ArrayStructure,
    x: int = Query(ge=0),
    y: int = Query(ge=0),
    band: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    """Raw (scaled) value at (x, y). Special-constant pixels return null."""
    data = _plane(label_id, structure_index, s, band)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if y >= data.shape[0] or x >= data.shape[1]:
        raise HTTPException(status_code=400, detail="Coordinates out of bounds")
    value = float(data[y, x])
    return {"x": x, "y": y, "band": band or 0, "value": value if np.isfinite(value) else None}
