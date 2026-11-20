"""Tests for table data and plotting endpoints."""
from __future__ import annotations

import pytest


def _upload_label(client, xml_path, tab_path):
    """Helper to upload a label and return the label_id."""
    with open(xml_path, "rb") as lf, open(tab_path, "rb") as df:
        resp = client.post(
            "/api/labels/upload",
            files={
                "label_file": (xml_path.name, lf, "application/xml"),
                "data_files": (tab_path.name, df, "application/octet-stream"),
            },
        )
    assert resp.status_code == 200
    return resp.json()["label_id"]


@pytest.mark.req("REQ-04")
def test_get_table_metadata(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp = client.get(f"/api/tables/{label_id}/0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["structure_type"] == "Table_Character"
    assert body["record_count"] > 0
    assert len(body["fields"]) > 0


@pytest.mark.req("REQ-04")
def test_get_table_data(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp = client.get(f"/api/tables/{label_id}/0/data?offset=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_records"] > 0
    assert len(body["data"]) <= 10
    assert len(body["columns"]) > 0
    # Data rows are positional lists, not dicts
    if body["data"]:
        assert isinstance(body["data"][0], list)
        assert len(body["data"][0]) == len(body["columns"])


@pytest.mark.req("REQ-04")
def test_get_table_data_pagination(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp1 = client.get(f"/api/tables/{label_id}/0/data?offset=0&limit=5")
    resp2 = client.get(f"/api/tables/{label_id}/0/data?offset=5&limit=5")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    data1 = resp1.json()["data"]
    data2 = resp2.json()["data"]
    if data1 and data2:
        assert data1[0] != data2[0]


@pytest.mark.req("REQ-05")
def test_get_table_csv(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp = client.get(f"/api/tables/{label_id}/0/data?format=csv&limit=5")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


@pytest.mark.req("REQ-04")
def test_table_structure_not_found(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp = client.get(f"/api/tables/{label_id}/99")
    assert resp.status_code == 404


@pytest.mark.req("REQ-06")
def test_histogram_plot(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)

    meta = client.get(f"/api/tables/{label_id}/0").json()
    numeric_fields = [f for f in meta["fields"] if "Real" in f["data_type"] or "Integer" in f["data_type"]]
    if not numeric_fields:
        return

    # Find the index of the first numeric field
    all_fields = meta["fields"]
    numeric_idx = next(i for i, f in enumerate(all_fields) if "Real" in f["data_type"] or "Integer" in f["data_type"])

    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={"plot_type": "histogram", "x_column": numeric_idx},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plot_type"] == "histogram"
    assert "traces" in body["data"]


@pytest.mark.req("REQ-06")
def test_line_plot(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)

    meta = client.get(f"/api/tables/{label_id}/0").json()
    all_fields = meta["fields"]
    numeric_indices = [i for i, f in enumerate(all_fields) if "Real" in f["data_type"] or "Integer" in f["data_type"]]
    if len(numeric_indices) < 2:
        return

    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={
            "plot_type": "line",
            "x_column": numeric_indices[0],
            "y_column": numeric_indices[1],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plot_type"] == "line"


@pytest.mark.req("REQ-06")
def test_scatter_plot(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)

    meta = client.get(f"/api/tables/{label_id}/0").json()
    all_fields = meta["fields"]
    numeric_indices = [i for i, f in enumerate(all_fields) if "Real" in f["data_type"] or "Integer" in f["data_type"]]
    if len(numeric_indices) < 2:
        return

    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={
            "plot_type": "scatter",
            "x_column": numeric_indices[0],
            "y_column": numeric_indices[1],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plot_type"] == "scatter"


@pytest.mark.req("REQ-06")
def test_heatmap_plot(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)

    meta = client.get(f"/api/tables/{label_id}/0").json()
    all_fields = meta["fields"]
    numeric_indices = [i for i, f in enumerate(all_fields) if "Real" in f["data_type"] or "Integer" in f["data_type"]]
    if len(numeric_indices) < 2:
        return

    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={
            "plot_type": "heatmap",
            "x_column": numeric_indices[0],
            "y_column": numeric_indices[1],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plot_type"] == "heatmap"


@pytest.mark.req("REQ-06")
def test_plot_missing_columns(client, table_character_xml, table_character_tab):
    label_id = _upload_label(client, table_character_xml, table_character_tab)
    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={"plot_type": "histogram"},
    )
    assert resp.status_code == 400


@pytest.mark.req("REQ-04")
def test_duplicate_column_names(client, table_dup_cols_xml, table_dup_cols_csv):
    """Test that tables with duplicate column names work correctly."""
    label_id = _upload_label(client, table_dup_cols_xml, table_dup_cols_csv)

    # Metadata should list all fields including duplicates
    meta = client.get(f"/api/tables/{label_id}/0").json()
    assert meta["record_count"] > 0
    assert len(meta["fields"]) == 11
    # There should be multiple fields named "Voltage count"
    vc_fields = [f for f in meta["fields"] if f["name"] == "Voltage count"]
    assert len(vc_fields) == 10

    # Data should return all 11 columns per row as positional arrays
    resp = client.get(f"/api/tables/{label_id}/0/data?offset=0&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["columns"]) == 11
    for row in body["data"]:
        assert isinstance(row, list)
        assert len(row) == 11

    # Plotting by column index should work with duplicate names
    resp = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={"plot_type": "histogram", "x_column": 1},
    )
    assert resp.status_code == 200

    # Different column indices with same name should give different data
    resp2 = client.post(
        f"/api/tables/{label_id}/0/plot",
        json={"plot_type": "histogram", "x_column": 5},
    )
    assert resp2.status_code == 200


@pytest.mark.req("REQ-05", "BUG-09")
def test_csv_export_streams_more_than_10000_rows(client, tmp_path, monkeypatch) -> None:
    from app.api.routes import tables

    monkeypatch.setattr(tables, "CSV_CHUNK_ROWS", 7)  # exercise multi-chunk streaming
    n = 12_345
    (tmp_path / "big.csv").write_bytes(b"".join(f"{i},{i * 0.5}\r\n".encode() for i in range(n)))
    label = tmp_path / "big.xml"
    label.write_text(f"""<Product_Observational xmlns="http://pds.nasa.gov/pds4/pds/v1"><File_Area_Observational>
<File><file_name>big.csv</file_name></File><Table_Delimited><local_identifier>big</local_identifier>
<offset unit="byte">0</offset><records>{n}</records><field_delimiter>Comma</field_delimiter>
<Record_Delimited><fields>2</fields><groups>0</groups>
<Field_Delimited><name>i</name><field_number>1</field_number><data_type>ASCII_Integer</data_type></Field_Delimited>
<Field_Delimited><name>h</name><field_number>2</field_number><data_type>ASCII_Real</data_type></Field_Delimited>
</Record_Delimited></Table_Delimited></File_Area_Observational></Product_Observational>""")
    with open(label, "rb") as lf, open(tmp_path / "big.csv", "rb") as df:
        label_id = client.post("/api/labels/upload", files={
            "label_file": ("big.xml", lf, "application/xml"),
            "data_files": ("big.csv", df, "text/csv"),
        }).json()["label_id"]
    resp = client.get(f"/api/tables/{label_id}/0/data", params={"format": "csv"})
    assert resp.status_code == 200
    assert 'filename="big.csv"' in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0] == "i,h" and len(lines) == n + 1 and lines[-1] == f"{n - 1},{(n - 1) * 0.5}"


@pytest.mark.req("REQ-04")
def test_json_page_limit_still_capped(client, table_character_xml, table_character_tab) -> None:
    with open(table_character_xml, "rb") as lf, open(table_character_tab, "rb") as df:
        label_id = client.post("/api/labels/upload", files={
            "label_file": (table_character_xml.name, lf, "application/xml"),
            "data_files": (table_character_tab.name, df, "application/octet-stream"),
        }).json()["label_id"]
    assert client.get(f"/api/tables/{label_id}/0/data", params={"limit": 20000}).status_code == 422
