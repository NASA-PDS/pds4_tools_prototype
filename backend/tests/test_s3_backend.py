"""S3 backend: ranged reads, pagination, prefix confinement, in-place viewing (moto-mocked)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import boto3
import numpy as np
import pytest
from moto import mock_aws

from app.services.storage import S3StorageBackend, register_backend

BUCKET = "pds-test"


class SpyClient:
    """Wraps a boto3 client and records get_object calls."""

    def __init__(self, client: object) -> None:
        self._client = client
        self.get_calls: list[dict] = []

    def get_object(self, **kwargs):  # noqa: ANN003
        self.get_calls.append(kwargs)
        return self._client.get_object(**kwargs)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


@pytest.fixture
def s3() -> Iterator[tuple[S3StorageBackend, SpyClient, object]]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        spy = SpyClient(client)
        backend = S3StorageBackend(BUCKET, prefix="archive", client=spy)
        register_backend("s3", backend)
        yield backend, spy, client


def _put_image_product(client, key_dir: str, n_bands: int = 4) -> np.ndarray:
    cube = np.arange(n_bands * 3 * 5, dtype=">i2").reshape(n_bands, 3, 5)
    client.put_object(Bucket=BUCKET, Key=f"{key_dir}/cube.img", Body=cube.tobytes())
    client.put_object(Bucket=BUCKET, Key=f"{key_dir}/cube.xml", Body=f"""<Product_Observational
 xmlns="http://pds.nasa.gov/pds4/pds/v1"><File_Area_Observational><File><file_name>cube.img</file_name></File>
<Array_3D_Spectrum><name>cube</name><offset unit="byte">0</offset><axes>3</axes>
<axis_index_order>Last Index Fastest</axis_index_order>
<Element_Array><data_type>SignedMSB2</data_type></Element_Array>
<Axis_Array><axis_name>Band</axis_name><elements>{n_bands}</elements><sequence_number>1</sequence_number></Axis_Array>
<Axis_Array><axis_name>Line</axis_name><elements>3</elements><sequence_number>2</sequence_number></Axis_Array>
<Axis_Array><axis_name>Sample</axis_name><elements>5</elements><sequence_number>3</sequence_number></Axis_Array>
</Array_3D_Spectrum></File_Area_Observational></Product_Observational>""".encode())
    return cube


@pytest.mark.req("REQ-13", "REQ-02")
def test_s3_listing_is_paginated(s3) -> None:
    backend, _, client = s3
    for i in range(1105):
        client.put_object(Bucket=BUCKET, Key=f"archive/many/f{i:05d}.dat", Body=b"x")
    entries = backend.list_directory("s3://pds-test/archive/many")
    assert len(entries) == 1105


@pytest.mark.req("REQ-13", "REQ-14")
def test_s3_paths_confined_to_prefix(s3) -> None:
    backend, _, client = s3
    client.put_object(Bucket=BUCKET, Key="secret/data.xml", Body=b"<x/>")
    assert backend.file_exists("s3://pds-test/secret/data.xml") is False
    assert backend.file_exists("s3://pds-test/archive/../secret/data.xml") is False
    with pytest.raises(FileNotFoundError):
        backend.list_directory("s3://pds-test/secret")
    assert backend.get_parent("s3://pds-test/archive") is None


@pytest.mark.req("REQ-13")
def test_s3_read_range(s3) -> None:
    backend, spy, client = s3
    client.put_object(Bucket=BUCKET, Key="archive/a.bin", Body=bytes(range(100)))
    assert backend.read_range("s3://pds-test/archive/a.bin", 10, 5) == bytes(range(10, 15))
    assert spy.get_calls[-1]["Range"] == "bytes=10-14"


@pytest.mark.req("REQ-13", "REQ-07", "REQ-15", "BUG-07")
def test_open_s3_product_reads_only_selected_band(client, s3) -> None:
    _, spy, s3client = s3
    cube = _put_image_product(s3client, "archive/p1")
    resp = client.post("/api/browse/open", params={"source": "s3", "path": "s3://pds-test/archive/p1/cube.xml"})
    assert resp.status_code == 200, resp.text
    label_id = resp.json()["label_id"]
    spy.get_calls.clear()

    meta = client.get(f"/api/images/{label_id}/0").json()
    assert (meta["bands"], meta["height"], meta["width"], meta["band_axis"]) == (4, 3, 5, 0)

    pixel = client.get(f"/api/images/{label_id}/0/pixel", params={"x": 4, "y": 2, "band": 2}).json()
    assert pixel["value"] == float(cube[2, 2, 4])
    # Exactly one ranged GET covering just band 2 (3*5 int16 = 30 bytes at offset 2*30)
    assert [c.get("Range") for c in spy.get_calls] == ["bytes=60-89"]


@pytest.mark.req("REQ-13", "REQ-04")
def test_open_s3_delimited_table_streams(client, s3, tmp_path: Path) -> None:
    _, _, s3client = s3
    s3client.put_object(Bucket=BUCKET, Key="archive/t/t.csv", Body=b"1,2.5\r\n2,3.5\r\n3,4.5\r\n")
    s3client.put_object(Bucket=BUCKET, Key="archive/t/t.xml", Body=b"""<Product_Observational
 xmlns="http://pds.nasa.gov/pds4/pds/v1"><File_Area_Observational><File><file_name>t.csv</file_name></File>
<Table_Delimited><offset unit="byte">0</offset><records>3</records><field_delimiter>Comma</field_delimiter>
<Record_Delimited><fields>2</fields><groups>0</groups>
<Field_Delimited><name>a</name><field_number>1</field_number><data_type>ASCII_Integer</data_type></Field_Delimited>
<Field_Delimited><name>b</name><field_number>2</field_number><data_type>ASCII_Real</data_type></Field_Delimited>
</Record_Delimited></Table_Delimited></File_Area_Observational></Product_Observational>""")
    label_id = client.post("/api/browse/open", params={"source": "s3", "path": "s3://pds-test/archive/t/t.xml"}).json()[
        "label_id"]
    body = client.get(f"/api/tables/{label_id}/0/data", params={"offset": 1, "limit": 5}).json()
    assert body["data"] == [[2, 3.5], [3, 4.5]]


@pytest.mark.req("REQ-13")
def test_s3_missing_data_file_returns_404(client, s3) -> None:
    _, _, s3client = s3
    _put_image_product(s3client, "archive/p2")
    s3client.delete_object(Bucket=BUCKET, Key="archive/p2/cube.img")
    label_id = client.post("/api/browse/open", params={"source": "s3", "path": "s3://pds-test/archive/p2/cube.xml"}).json()[
        "label_id"]
    assert client.get(f"/api/images/{label_id}/0/statistics").status_code == 404
