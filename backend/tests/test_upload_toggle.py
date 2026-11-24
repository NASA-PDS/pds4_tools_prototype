"""REQ-17: label upload is off unless the operator enables it."""
from __future__ import annotations

import importlib

import pytest

from app import config
from app.services.storage import LocalFilesystemBackend, get_backend, register_backend

from .conftest import TABLE_CHARACTER_TAB, TABLE_CHARACTER_XML, TEST_DATA_DIR


def _upload(client):
    with open(TABLE_CHARACTER_XML, "rb") as lf, open(TABLE_CHARACTER_TAB, "rb") as df:
        return client.post("/api/labels/upload", files=[
            ("label_file", (TABLE_CHARACTER_XML.name, lf)),
            ("data_files", (TABLE_CHARACTER_TAB.name, df)),
        ])


@pytest.mark.req("REQ-17")
@pytest.mark.parametrize("value,expected", [
    (None, False), ("", False), ("0", False), ("false", False),
    ("1", True), ("true", True), ("YES", True), ("on", True),
])
def test_upload_flag_parsing(monkeypatch, value, expected) -> None:
    if value is None:
        monkeypatch.delenv("PDS_ENABLE_UPLOAD", raising=False)
    else:
        monkeypatch.setenv("PDS_ENABLE_UPLOAD", value)
    try:
        assert importlib.reload(config).UPLOAD_ENABLED is expected
    finally:
        monkeypatch.delenv("PDS_ENABLE_UPLOAD", raising=False)
        importlib.reload(config)


@pytest.mark.req("REQ-17", "REQ-14")
def test_upload_rejected_when_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_ENABLED", False)
    sessions_before = set(config.UPLOAD_DIR.glob("session_*"))

    resp = _upload(client)

    assert resp.status_code == 403
    assert client.get("/api/labels").json() == []
    assert set(config.UPLOAD_DIR.glob("session_*")) == sessions_before


@pytest.mark.req("REQ-17", "REQ-01")
def test_upload_works_when_enabled(client) -> None:
    resp = _upload(client)
    assert resp.status_code == 200
    assert resp.json()["filename"] == TABLE_CHARACTER_XML.name


@pytest.mark.req("REQ-17")
@pytest.mark.parametrize("enabled", [True, False])
def test_config_endpoint_reports_upload_flag(client, monkeypatch, enabled) -> None:
    monkeypatch.setattr(config, "UPLOAD_ENABLED", enabled)
    assert client.get("/api/config").json()["upload_enabled"] is enabled


@pytest.mark.req("REQ-17", "REQ-02")
def test_browse_open_works_when_upload_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_ENABLED", False)
    previous = get_backend("local")
    register_backend("local", LocalFilesystemBackend(root_path=str(TEST_DATA_DIR)))
    try:
        resp = client.post("/api/browse/open", params={"source": "local", "path": str(TABLE_CHARACTER_XML)})
    finally:
        if previous is not None:
            register_backend("local", previous)
    assert resp.status_code == 200
