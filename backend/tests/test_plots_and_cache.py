"""Plot scalability (server-side binning, decimation, aligned pairs) and decoded-data caching."""
from __future__ import annotations

import pytest

from app.services import data_cache as data_cache_module
from app.services.table_service import compute_heatmap, compute_histogram, compute_line_plot, compute_scatter_plot


@pytest.mark.req("REQ-06", "REQ-15")
def test_histogram_is_binned_server_side() -> None:
    rows = [[float(i)] for i in range(100_000)]
    trace = compute_histogram(rows, 0, "x", nbins=20)["data"][0]
    assert trace["type"] == "bar"
    assert len(trace["x"]) == 20 and sum(trace["y"]) == 100_000


@pytest.mark.req("REQ-06", "REQ-15")
def test_heatmap_is_binned_server_side() -> None:
    rows = [[float(i), float(i % 7)] for i in range(10_000)]
    trace = compute_heatmap(rows, 0, 1, "x", "y", nbins=10)["data"][0]
    assert trace["type"] == "heatmap"
    assert len(trace["z"]) == 10 and sum(map(sum, trace["z"])) == 10_000


@pytest.mark.req("REQ-06", "REQ-15")
def test_line_plot_decimated_above_limit() -> None:
    rows = [[float(i), float(i)] for i in range(10_000)]
    result = compute_line_plot(rows, 0, 1, "x", "y", max_points=1000)
    assert len(result["data"][0]["x"]) <= 1000
    assert "every 10th point" in result["layout"]["title"]


@pytest.mark.req("REQ-06", "BUG-06")
def test_line_and_scatter_keep_pairs_aligned_with_nulls() -> None:
    rows = [[1.0, 10.0], [None, 20.0], [3.0, None], [4.0, 40.0]]
    for fn in (compute_line_plot, compute_scatter_plot):
        trace = fn(rows, 0, 1, "x", "y")["data"][0]
        assert list(zip(trace["x"], trace["y"])) == [(1.0, 10.0), (4.0, 40.0)]


@pytest.mark.req("REQ-15")
def test_decoded_image_is_cached_between_requests(client, array_2d_image_xml, array_2d_image_data, monkeypatch) -> None:
    from app.api.routes import images

    data_cache_module.data_cache.clear()
    calls = {"n": 0}
    real = images.read_array_data

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(images, "read_array_data", counting)
    with open(array_2d_image_xml, "rb") as lf, open(array_2d_image_data, "rb") as df:
        label_id = client.post("/api/labels/upload", files={
            "label_file": (array_2d_image_xml.name, lf, "application/xml"),
            "data_files": (array_2d_image_data.name, df, "application/octet-stream"),
        }).json()["label_id"]

    client.get(f"/api/images/{label_id}/0/statistics")
    client.post(f"/api/images/{label_id}/0/render", json={"colormap": "viridis"})
    client.post(f"/api/images/{label_id}/0/render", json={"colormap": "hot", "stretch": "log"})
    client.get(f"/api/images/{label_id}/0/pixel", params={"x": 1, "y": 1})
    assert calls["n"] == 1


@pytest.mark.req("REQ-15")
def test_cache_evicts_by_size() -> None:
    import numpy as np

    cache = data_cache_module.DataCache(max_bytes=3000)
    for i in range(5):
        cache.get_or_load(i, lambda: np.zeros(1000, dtype="u1"))
    assert len(cache) == 3 and cache.size_bytes <= 3000
