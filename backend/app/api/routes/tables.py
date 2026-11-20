"""Table data and plotting endpoints."""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app import config
from app.api.deps import TableStructure
from app.models.schemas import FieldInfo, PlotDataResponse, PlotSpec, TableDataResponse, TableMetadata
from app.services.data_cache import data_cache
from app.services.label_parser import iter_table_rows, read_table_data
from app.services.table_service import compute_heatmap, compute_histogram, compute_line_plot, compute_scatter_plot

router = APIRouter()


def _read(s: dict[str, Any], offset: int, limit: int | None) -> list[list[Any]]:
    try:
        return read_table_data(s, offset=offset, limit=limit)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read table data: {e}")


@router.get("/{label_id}/{structure_index}", response_model=TableMetadata)
def get_table_metadata(label_id: str, structure_index: int, s: TableStructure) -> TableMetadata:
    """Get metadata for a specific table structure."""
    return TableMetadata(
        label_id=label_id,
        structure_index=structure_index,
        name=s["name"],
        structure_type=s["structure_type"],
        record_count=s.get("record_count") or 0,
        fields=[
            FieldInfo(name=f["name"], field_number=f["field_number"], data_type=f["data_type"],
                      unit=f.get("unit"), description=f.get("description"))
            for f in s.get("fields", [])
        ],
    )


@router.get("/{label_id}/{structure_index}/data", response_model=TableDataResponse)
def get_table_data(
    label_id: str,
    structure_index: int,
    s: TableStructure,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, description="JSON: max 10000 (default 100). CSV: default all rows"),
    format: str = Query(default="json", pattern="^(json|csv)$"),
) -> TableDataResponse | StreamingResponse:
    """Get one page of table data (ranged read), or stream rows as CSV with format=csv."""
    columns = [f["name"] for f in s.get("fields", [])]

    if format == "csv":
        total = s.get("record_count") or 0
        end = total if limit is None else min(total, offset + limit)
        _read(s, offset, 1)  # fail fast (404/500) before the streaming response starts
        return _csv_stream(s, columns, offset, end)

    if limit is None:
        limit = 100
    if limit > 10000:
        raise HTTPException(status_code=422, detail="limit must be <= 10000 for JSON; use format=csv for bulk export")
    rows = _read(s, offset, limit)

    return TableDataResponse(
        label_id=label_id,
        structure_index=structure_index,
        total_records=s.get("record_count") or 0,
        offset=offset,
        limit=limit,
        columns=columns,
        data=rows,
    )


@router.post("/{label_id}/{structure_index}/plot", response_model=PlotDataResponse)
def create_plot(label_id: str, structure_index: int, spec: PlotSpec, s: TableStructure) -> PlotDataResponse:
    """Generate plot-ready data. Histograms/heatmaps are binned server-side; line/scatter are decimated."""
    fields = s.get("fields", [])

    def col_name(idx: int) -> str:
        return fields[idx]["name"] if 0 <= idx < len(fields) else f"Column {idx}"

    def check(*cols: int | None) -> None:
        for c in cols:
            if c is not None and not 0 <= c < len(fields):
                raise HTTPException(status_code=400, detail=f"Column index {c} out of range")

    needs_y = spec.plot_type in ("line", "scatter", "heatmap")
    if spec.plot_type not in ("histogram", "line", "scatter", "heatmap"):
        raise HTTPException(status_code=400, detail=f"Unknown plot type: {spec.plot_type}")
    if spec.x_column is None or (needs_y and spec.y_column is None):
        need = "x_column and y_column" if needs_y else "x_column"
        raise HTTPException(status_code=400, detail=f"{need} required for {spec.plot_type}")
    check(spec.x_column, spec.y_column, spec.color_column)

    all_data = data_cache.get_or_load(("table", label_id, structure_index), lambda: _read(s, 0, None))

    x, y = spec.x_column, spec.y_column
    if spec.plot_type == "histogram":
        result = compute_histogram(all_data, x, col_name(x), nbins=spec.nbins or 30, trace_color=spec.trace_color)
    elif spec.plot_type == "line":
        result = compute_line_plot(all_data, x, y, col_name(x), col_name(y),
                                   trace_color=spec.trace_color, max_points=config.PLOT_MAX_POINTS)
    elif spec.plot_type == "scatter":
        result = compute_scatter_plot(
            all_data, x, y, col_name(x), col_name(y),
            spec.color_column, col_name(spec.color_column) if spec.color_column is not None else None,
            trace_color=spec.trace_color, max_points=config.PLOT_MAX_POINTS,
        )
    else:
        result = compute_heatmap(all_data, x, y, col_name(x), col_name(y))

    return PlotDataResponse(
        plot_type=spec.plot_type,
        data={"traces": result.get("data", [])},
        layout=result.get("layout", {}),
    )


CSV_CHUNK_ROWS = 10_000


def _csv_stream(s: dict[str, Any], columns: list[str], start: int, end: int) -> StreamingResponse:
    """Stream CSV in chunks so exports of any size use bounded memory."""

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        # One sequential pass over the requested rows; flush every CSV_CHUNK_ROWS.
        for i, row in enumerate(iter_table_rows(s, offset=start, limit=end - start), 1):
            writer.writerow(row)
            if i % CSV_CHUNK_ROWS == 0:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    name = (s.get("local_identifier") or s.get("name") or "table").replace("/", "_").replace('"', "")
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )
