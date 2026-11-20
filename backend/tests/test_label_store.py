"""Persistent label store: survives restarts, shared across workers, expires and cleans up."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.services.label_store import LabelStore


def _store(tmp_path: Path, ttl: int = 3600) -> LabelStore:
    return LabelStore(tmp_path / "labels", tmp_path / "uploads", ttl)


@pytest.mark.req("REQ-12")
def test_label_visible_to_a_second_store_instance(tmp_path: Path) -> None:
    """A new process (or worker) pointed at the same directory sees stored labels."""
    label_id = _store(tmp_path).put({"filename": "a.xml", "structures": []})
    assert _store(tmp_path).get(label_id)["filename"] == "a.xml"


@pytest.mark.req("REQ-12")
def test_ids_are_full_uuids_and_validated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    label_id = store.put({"filename": "a.xml"})
    assert len(label_id) == 32
    assert store.get("../../etc/passwd") is None
    assert store.get("deadbeef") is None


@pytest.mark.req("REQ-12")
def test_expired_labels_and_uploads_are_cleaned_up(tmp_path: Path) -> None:
    store = _store(tmp_path, ttl=60)
    old_id = store.put({"filename": "old.xml"})
    new_id = store.put({"filename": "new.xml"})
    old_session = store.new_upload_session()
    (old_session / "data.img").write_bytes(b"x")
    past = time.time() - 3600
    os.utime(store.label_dir / f"{old_id}.json", (past, past))
    os.utime(old_session, (past, past))

    assert store.get(old_id) is None  # expired records are never served
    assert store.cleanup() == 2
    assert not old_session.exists()
    assert store.get(new_id) is not None


@pytest.mark.req("REQ-12")
def test_access_refreshes_expiry(tmp_path: Path) -> None:
    store = _store(tmp_path, ttl=600)
    session = store.new_upload_session()
    label_id = store.put({"filename": "a.xml", "upload_session": session.name})
    stale = time.time() - 300
    os.utime(store.label_dir / f"{label_id}.json", (stale, stale))
    os.utime(session, (stale, stale))
    assert store.get(label_id) is not None
    assert (store.label_dir / f"{label_id}.json").stat().st_mtime > stale + 200
    assert session.stat().st_mtime > stale + 200


@pytest.mark.req("REQ-12", "REQ-01")
def test_upload_size_limit(client, table_character_xml, monkeypatch) -> None:
    from app import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)
    resp = client.post(
        "/api/labels/upload",
        files={
            "label_file": (table_character_xml.name, table_character_xml.read_bytes(), "application/xml"),
            "data_files": ("big.tab", b"x" * 5000, "application/octet-stream"),
        },
    )
    assert resp.status_code == 413


@pytest.mark.req("REQ-12", "REQ-14")
def test_uploads_source_is_not_browsable(client) -> None:
    names = [s["name"] for s in client.get("/api/browse/sources").json()]
    assert "_uploads" not in names
    assert client.get("/api/browse/list", params={"source": "_uploads"}).status_code == 404
