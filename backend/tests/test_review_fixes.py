"""Regression tests for PR review findings: delimited row index, single-pass CSV export,
hidden S3 entries, scheduled cleanup, and traceability handling of skipped tests."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from app.services import label_parser
from app.services.label_parser import iter_table_rows, parse_label_file, read_table_data
from app.services.label_store import LabelStore

from .test_s3_backend import BUCKET, s3  # noqa: F401  (fixture)

NS = 'xmlns="http://pds.nasa.gov/pds4/pds/v1"'
REPO_ROOT = Path(__file__).resolve().parents[2]


def _delimited(tmp_path: Path, n: int) -> dict:
    (tmp_path / "t.csv").write_bytes(b"".join(f"{i},{i * 0.5}\r\n".encode() for i in range(n)))
    (tmp_path / "t.xml").write_text(f"""<Product_Observational {NS}><File_Area_Observational>
<File><file_name>t.csv</file_name></File>
<Table_Delimited><offset unit="byte">0</offset><records>{n}</records><field_delimiter>Comma</field_delimiter>
<Record_Delimited><fields>2</fields><groups>0</groups>
<Field_Delimited><name>a</name><field_number>1</field_number><data_type>ASCII_Integer</data_type></Field_Delimited>
<Field_Delimited><name>b</name><field_number>2</field_number><data_type>ASCII_Real</data_type></Field_Delimited>
</Record_Delimited></Table_Delimited></File_Area_Observational></Product_Observational>""")
    return parse_label_file(tmp_path / "t.xml")["structures"][0]


class _CountingBackend:
    """Local reader that records where each stream starts and how many bytes it yields."""

    def __init__(self) -> None:
        self.opens: list[int] = []
        self.bytes_read = 0

    def file_exists(self, path: str) -> bool:
        return Path(path).is_file()

    def open_stream(self, path: str, offset: int = 0):
        self.opens.append(offset)
        outer = self
        f = open(path, "rb")  # noqa: SIM115
        f.seek(offset)

        class _Counted:
            def __iter__(self):
                for line in f:
                    outer.bytes_read += len(line)
                    yield line

            def peek(self, n: int = 0) -> bytes:  # marks it as already buffered
                return f.peek(n)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                f.close()

        return _Counted()


@pytest.mark.req("REQ-04", "REQ-15")
def test_delimited_paging_starts_near_requested_row(tmp_path: Path, monkeypatch) -> None:
    s = _delimited(tmp_path, 5_000)
    backend = _CountingBackend()
    monkeypatch.setattr(label_parser, "_reader", lambda _s: (backend, s["data_file"]))

    assert read_table_data(s, offset=4_500, limit=2) == [[4500, 2250.0], [4501, 2250.5]]
    first_scan = backend.bytes_read
    backend.bytes_read = 0

    # Second request deep in the table starts at the nearest checkpoint, not byte 0.
    assert read_table_data(s, offset=4_200, limit=1) == [[4200, 2100.0]]
    assert backend.opens[-1] > 0
    assert backend.bytes_read < first_scan / 10


@pytest.mark.req("REQ-05", "BUG-09")
def test_csv_export_reads_delimited_table_once(tmp_path: Path, monkeypatch) -> None:
    s = _delimited(tmp_path, 25_000)
    backend = _CountingBackend()
    monkeypatch.setattr(label_parser, "_reader", lambda _s: (backend, s["data_file"]))

    rows = list(iter_table_rows(s))
    assert len(rows) == 25_000 and rows[-1] == [24999, 12499.5]
    assert len(backend.opens) == 1
    assert backend.bytes_read == (tmp_path / "t.csv").stat().st_size


@pytest.mark.req("REQ-05", "BUG-09")
def test_csv_export_endpoint_streams_all_rows(client, tmp_path: Path) -> None:
    _delimited(tmp_path, 25_000)
    with open(tmp_path / "t.xml", "rb") as lf, open(tmp_path / "t.csv", "rb") as df:
        label_id = client.post("/api/labels/upload", files=[("label_file", ("t.xml", lf)),
                                                             ("data_files", ("t.csv", df))]).json()["label_id"]
    resp = client.get(f"/api/tables/{label_id}/0/data", params={"format": "csv"})
    lines = resp.text.splitlines()
    assert lines[0] == "a,b" and len(lines) == 25_001 and lines[-1] == "24999,12499.5"


@pytest.mark.req("REQ-02", "REQ-13")
def test_s3_listing_hides_dot_entries(s3) -> None:  # noqa: F811
    backend, _, client = s3
    for key in ("archive/d/.credentials", "archive/d/.hidden/x.xml", "archive/d/visible.xml",
                "archive/d/sub/y.xml"):
        client.put_object(Bucket=BUCKET, Key=key, Body=b"x")
    names = [e.name for e in backend.list_directory(f"s3://{BUCKET}/archive/d")]
    assert names == ["sub", "visible.xml"]


@pytest.mark.req("REQ-12")
def test_cleanup_runs_on_schedule_without_uploads(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    store = LabelStore(tmp_path / "labels", tmp_path / "uploads", ttl_seconds=60)
    label_id = store.put({"filename": "x.xml"})
    old = time.time() - 3600
    os.utime(store.label_dir / f"{label_id}.json", (old, old))

    monkeypatch.setattr(main, "label_store", store)
    monkeypatch.setattr(main, "CLEANUP_INTERVAL_SECONDS", 0.01)

    async def run() -> None:
        task = asyncio.create_task(main._periodic_cleanup())
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(run())
    assert store.get(label_id) is None
    assert not list(store.label_dir.glob("*.json"))


def _load_trace_matrix():
    spec = importlib.util.spec_from_file_location("trace_matrix", REPO_ROOT / "traceability" / "trace_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["trace_matrix"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.req("REQ-16")
def test_trace_matrix_does_not_pass_skipped_tests() -> None:
    tm = _load_trace_matrix()
    catalog = {"repository": "o/r", "items": {
        "REQ-A": {"type": "requirement", "title": "a"},
        "REQ-B": {"type": "requirement", "title": "b"},
    }}
    results = [
        {"keys": {"REQ-A"}, "status": "skipped", "suite": "s", "test": "t1"},
        {"keys": {"REQ-B"}, "status": "passed", "suite": "s", "test": "t2"},
    ]
    m = tm.build(catalog, results)
    assert m["items"]["REQ-A"]["status"] == "SKIPPED"
    assert m["items"]["REQ-B"]["status"] == "PASS"


@pytest.mark.req("REQ-13", "REQ-04")
def test_s3_delimited_paging_uses_bounded_ranges(s3, monkeypatch) -> None:  # noqa: F811
    from app.services import storage

    backend, spy, client = s3
    monkeypatch.setattr(storage, "STREAM_CHUNK_BYTES", 64)
    body = b"".join(f"{i},{i}.5\r\n".encode() for i in range(200))
    client.put_object(Bucket=BUCKET, Key="archive/t/t.csv", Body=body)
    with backend.open_stream(f"s3://{BUCKET}/archive/t/t.csv") as stream:
        first = [stream.readline() for _ in range(3)]
    assert first == [b"0,0.5\r\n", b"1,1.5\r\n", b"2,2.5\r\n"]
    ranges = [c.get("Range") for c in spy.get_calls]
    assert ranges and all(r and not r.endswith("-") for r in ranges)
    assert len(ranges) < len(body) // 64  # stopped early, did not read the whole object
