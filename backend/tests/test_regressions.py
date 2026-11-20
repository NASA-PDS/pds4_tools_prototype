"""Regression tests for issues found in the Nov 2026 code review."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.api.routes.labels import UPLOAD_DIR
from app.services.label_parser import parse_label_file, read_array_data, read_table_data

NS = 'xmlns="http://pds.nasa.gov/pds4/pds/v1"'


def _array_label(data_type: str) -> str:
    return f"""<Product_Observational {NS}><File_Area_Observational>
<File><file_name>a.img</file_name></File>
<Array_2D_Image><offset unit="byte">0</offset><axes>2</axes>
<axis_index_order>Last Index Fastest</axis_index_order>
<Element_Array><data_type>{data_type}</data_type></Element_Array>
<Axis_Array><axis_name>Line</axis_name><elements>2</elements><sequence_number>1</sequence_number></Axis_Array>
<Axis_Array><axis_name>Sample</axis_name><elements>3</elements><sequence_number>2</sequence_number></Axis_Array>
</Array_2D_Image></File_Area_Observational></Product_Observational>"""


@pytest.mark.parametrize(
    "data_type,np_dtype",
    [
        ("IEEE754LSBSingle", "<f4"),
        ("IEEE754LSBDouble", "<f8"),
        ("IEEE754MSBSingle", ">f4"),
        ("SignedLSB2", "<i2"),
        ("UnsignedLSB4", "<u4"),
        ("SignedMSB4", ">i4"),
    ],
)
@pytest.mark.req("REQ-11", "BUG-03")
def test_array_byte_order(tmp_path: Path, data_type: str, np_dtype: str) -> None:
    np.arange(6, dtype=np_dtype).tofile(tmp_path / "a.img")
    (tmp_path / "a.xml").write_text(_array_label(data_type))
    data = read_array_data(parse_label_file(tmp_path / "a.xml")["structures"][0])
    assert data.shape == (2, 3)
    assert data.ravel().tolist() == [0, 1, 2, 3, 4, 5]


@pytest.mark.req("REQ-11", "BUG-03")
def test_unknown_array_type_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / "a.img").write_bytes(b"\x00" * 64)
    (tmp_path / "a.xml").write_text(_array_label("ComplexLSB16"))
    with pytest.raises(ValueError, match="Unsupported"):
        read_array_data(parse_label_file(tmp_path / "a.xml")["structures"][0])


def _delimited_label(delimiter: str) -> str:
    return f"""<Product_Observational {NS}><File_Area_Observational>
<File><file_name>t.tab</file_name></File>
<Table_Delimited><offset unit="byte">0</offset><records>2</records>
<record_delimiter>Carriage-Return Line-Feed</record_delimiter><field_delimiter>{delimiter}</field_delimiter>
<Record_Delimited><fields>3</fields><groups>0</groups>
<Field_Delimited><name>a</name><field_number>1</field_number><data_type>ASCII_Integer</data_type></Field_Delimited>
<Field_Delimited><name>b</name><field_number>2</field_number><data_type>ASCII_Real</data_type></Field_Delimited>
<Field_Delimited><name>c</name><field_number>3</field_number><data_type>ASCII_String</data_type></Field_Delimited>
</Record_Delimited></Table_Delimited></File_Area_Observational></Product_Observational>"""


@pytest.mark.req("REQ-04", "BUG-04")
@pytest.mark.parametrize("name,char", [("Horizontal Tab", "\t"), ("Semicolon", ";"), ("Vertical Bar", "|")])
def test_delimited_honors_field_delimiter(tmp_path: Path, name: str, char: str) -> None:
    (tmp_path / "t.tab").write_bytes(f"1{char}2.5{char}x\r\n3{char}4.5{char}y\r\n".encode())
    (tmp_path / "t.xml").write_text(_delimited_label(name))
    rows = read_table_data(parse_label_file(tmp_path / "t.xml")["structures"][0])
    assert rows == [[1, 2.5, "x"], [3, 4.5, "y"]]


@pytest.mark.req("REQ-04", "BUG-04")
def test_delimited_quoted_comma(tmp_path: Path) -> None:
    (tmp_path / "t.tab").write_bytes(b'1,2.5,"hello, mars"\r\n')
    (tmp_path / "t.xml").write_text(_delimited_label("Comma").replace("<records>2", "<records>1"))
    rows = read_table_data(parse_label_file(tmp_path / "t.xml")["structures"][0])
    assert rows == [[1, 2.5, "hello, mars"]]


@pytest.mark.req("REQ-04", "REQ-11", "BUG-03")
def test_binary_table_lsb_and_char_fields(tmp_path: Path) -> None:
    rec = np.array([7], "<i2").tobytes() + np.array([1.5], "<f8").tobytes() + b"AB"
    (tmp_path / "b.dat").write_bytes(rec * 2)
    (tmp_path / "b.xml").write_text(f"""<Product_Observational {NS}><File_Area_Observational>
<File><file_name>b.dat</file_name></File>
<Table_Binary><offset unit="byte">0</offset><records>2</records>
<Record_Binary><fields>3</fields><groups>0</groups><record_length unit="byte">12</record_length>
<Field_Binary><name>i</name><field_number>1</field_number><field_location unit="byte">1</field_location>
<data_type>SignedLSB2</data_type><field_length unit="byte">2</field_length></Field_Binary>
<Field_Binary><name>d</name><field_number>2</field_number><field_location unit="byte">3</field_location>
<data_type>IEEE754LSBDouble</data_type><field_length unit="byte">8</field_length></Field_Binary>
<Field_Binary><name>s</name><field_number>3</field_number><field_location unit="byte">11</field_location>
<data_type>ASCII_String</data_type><field_length unit="byte">2</field_length></Field_Binary>
</Record_Binary></Table_Binary></File_Area_Observational></Product_Observational>""")
    rows = read_table_data(parse_label_file(tmp_path / "b.xml")["structures"][0])
    assert rows == [[7, 1.5, "AB"], [7, 1.5, "AB"]]


@pytest.mark.req("REQ-14", "BUG-01")
@pytest.mark.parametrize("evil", ["../../../../tmp/pds4_pwned.txt", "/tmp/pds4_pwned.txt", "..\\..\\pds4_pwned.txt"])
def test_upload_filename_cannot_escape_session_dir(client, table_character_xml, evil: str) -> None:
    target = Path("/tmp/pds4_pwned.txt")
    target.unlink(missing_ok=True)
    resp = client.post(
        "/api/labels/upload",
        files={
            "label_file": (table_character_xml.name, table_character_xml.read_bytes(), "application/xml"),
            "data_files": (evil, b"owned", "text/plain"),
        },
    )
    assert resp.status_code == 200
    assert not target.exists()
    assert list(UPLOAD_DIR.rglob("pds4_pwned.txt")), "file should land inside the upload dir"
