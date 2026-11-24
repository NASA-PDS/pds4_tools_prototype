"""Table data service for generating plot-ready data from PDS4 tables."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def compute_histogram(
    data: list[list[Any]],
    column_index: int,
    column_name: str,
    nbins: int = 30,
    trace_color: str | None = None,
) -> dict[str, Any]:
    """Compute histogram data for a numeric column."""
    values = _extract_numeric(data, column_index)
    if not values:
        return {"data": [], "layout": {}}

    arr = np.array(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {"data": [], "layout": {}}

    # Bin on the server so payload size is O(nbins), not O(rows).
    counts, edges = np.histogram(arr, bins=nbins)
    centers = (edges[:-1] + edges[1:]) / 2
    return {
        "data": [{
            "type": "bar",
            "x": centers.tolist(),
            "y": counts.tolist(),
            "width": float(edges[1] - edges[0]) if len(edges) > 1 else None,
            "marker": {"color": trace_color or "#1052A5"},
        }],
        "layout": {
            "title": f"Histogram of {column_name}",
            "xaxis": {"title": column_name},
            "yaxis": {"title": "Count"},
        },
    }


def compute_line_plot(
    data: list[list[Any]],
    x_index: int,
    y_index: int,
    x_name: str,
    y_name: str,
    trace_color: str | None = None,
    max_points: int = 50_000,
) -> dict[str, Any]:
    """Compute line plot data for two columns (evenly decimated above max_points)."""
    # Extract x/y together so a null in one column drops the whole row and pairs stay aligned.
    rows = [r for r in data if _value(r, x_index) is not None and _value(r, y_index) is not None]
    if not rows:
        return {"data": [], "layout": {}}

    step = _decimation_step(len(rows), max_points)
    rows = rows[::step]
    x_vals = [_value(r, x_index) for r in rows]
    y_vals = [_value(r, y_index) for r in rows]

    return {
        "data": [{
            "type": "scatter",
            "mode": "lines",
            "x": x_vals,
            "y": y_vals,
            "line": {"color": trace_color or "#1052A5", "width": 2},
        }],
        "layout": {
            "title": _title(f"{y_name} vs {x_name}", step),
            "xaxis": {"title": x_name},
            "yaxis": {"title": y_name},
        },
    }


def compute_scatter_plot(
    data: list[list[Any]],
    x_index: int,
    y_index: int,
    x_name: str,
    y_name: str,
    color_index: int | None = None,
    color_name: str | None = None,
    trace_color: str | None = None,
    max_points: int = 50_000,
) -> dict[str, Any]:
    """Compute scatter plot data for two columns (evenly decimated above max_points)."""
    # Extract x/y together so a null in one column drops the whole row and pairs stay aligned.
    rows = [r for r in data if _value(r, x_index) is not None and _value(r, y_index) is not None]
    if not rows:
        return {"data": [], "layout": {}}

    step = _decimation_step(len(rows), max_points)
    rows = rows[::step]
    x_vals = [_value(r, x_index) for r in rows]
    y_vals = [_value(r, y_index) for r in rows]

    trace: dict[str, Any] = {
        "type": "scatter",
        "mode": "markers",
        "x": x_vals,
        "y": y_vals,
        "marker": {"color": trace_color or "#1052A5", "size": 5, "opacity": 0.7},
    }

    if color_index is not None:
        c_vals = [_value(r, color_index) for r in rows]
        if any(isinstance(c, float) for c in c_vals):
            trace["marker"]["color"] = [c if isinstance(c, float) else None for c in c_vals]
            trace["marker"]["colorscale"] = "Viridis"
            trace["marker"]["showscale"] = True
            trace["marker"]["colorbar"] = {"title": color_name or f"Column {color_index}"}

    return {
        "data": [trace],
        "layout": {
            "title": _title(f"{y_name} vs {x_name}", step),
            "xaxis": {"title": x_name},
            "yaxis": {"title": y_name},
        },
    }


def compute_heatmap(
    data: list[list[Any]],
    x_index: int,
    y_index: int,
    x_name: str,
    y_name: str,
    nbins: int = 50,
) -> dict[str, Any]:
    """Compute 2D histogram / heatmap for two columns."""
    pairs = [(_value(r, x_index), _value(r, y_index)) for r in data]
    pairs = [(x, y) for x, y in pairs if isinstance(x, float) and isinstance(y, float)]
    if not pairs:
        return {"data": [], "layout": {}}

    x_arr = np.array([p[0] for p in pairs], dtype=float)
    y_arr = np.array([p[1] for p in pairs], dtype=float)

    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr = x_arr[mask]
    y_arr = y_arr[mask]

    if len(x_arr) == 0:
        return {"data": [], "layout": {}}

    counts, x_edges, y_edges = np.histogram2d(x_arr, y_arr, bins=nbins)
    return {
        "data": [{
            "type": "heatmap",
            "x": ((x_edges[:-1] + x_edges[1:]) / 2).tolist(),
            "y": ((y_edges[:-1] + y_edges[1:]) / 2).tolist(),
            "z": counts.T.tolist(),
            "colorscale": "Viridis",
        }],
        "layout": {
            "title": f"Heatmap: {y_name} vs {x_name}",
            "xaxis": {"title": x_name},
            "yaxis": {"title": y_name},
        },
    }


def _decimation_step(n: int, max_points: int) -> int:
    return max(1, -(-n // max_points)) if max_points > 0 else 1


def _title(base: str, step: int) -> str:
    return f"{base} (every {step}th point)" if step > 1 else base


def _extract_numeric(data: list[list[Any]], column_index: int) -> list[float]:
    """Extract numeric values from a column by index, skipping non-numeric entries."""
    values: list[float] = []
    for row in data:
        if column_index >= len(row):
            continue
        val = row[column_index]
        if val is None:
            continue
        try:
            fval = float(val)
            if math.isfinite(fval):
                values.append(fval)
        except (ValueError, TypeError):
            continue
    return values


def _value(row: list[Any], column_index: int) -> float | str | None:
    """A cell as a finite float, a non-empty string (e.g. datetime), or None."""
    if column_index >= len(row):
        return None
    val = row[column_index]
    if val is None:
        return None
    try:
        fval = float(val)
        return fval if math.isfinite(fval) else None
    except (ValueError, TypeError):
        text = str(val).strip()
        return text or None
