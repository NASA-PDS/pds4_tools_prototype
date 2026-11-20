"""Parser correctness: groups, scaling/special constants, 3D bands, hardened XML."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.label_parser import array_plane_shape, parse_label, read_array_data, read_table_data

NS = 'xmlns="http://pds.nasa.gov/pds4/pds/v1"'


def _write(tmp_path: Path, xml: str, data: bytes, data_name: str = "d.dat") -> Path:
    (tmp_path / data_name).write_bytes(data)
    label = tmp_path / "l.xml"
    label.write_text(f"<Product_Observational {NS}><File_Area_Observational><File><file_name>{data_name}</file_name>"
                     f"</File>{xml}</File_Area_Observational></Product_Observational>")
    return label


@pytest.mark.req("REQ-04", "BUG-05")
def test_repeated_group_fields_read_at_group_offsets(tmp_path: Path) -> None:
    # record: id(2) + group of 3 reps x [val(3)] at group_location 3, total 9 bytes, + CRLF
    records = b"01100200300\r\n02400500600\r\n"
    label = _write(tmp_path, """<Table_Character><offset unit="byte">0</offset><records>2</records>
<record_delimiter>Carriage-Return Line-Feed</record_delimiter>
<Record_Character><fields>1</fields><groups>1</groups><record_length unit="byte">13</record_length>
<Field_Character><name>id</name><field_number>1</field_number><field_location unit="byte">1</field_location>
<data_type>ASCII_Integer</data_type><field_length unit="byte">2</field_length></Field_Character>
<Group_Field_Character><group_number>1</group_number><repetitions>3</repetitions><fields>1</fields><groups>0</groups>
<group_location unit="byte">3</group_location><group_length unit="byte">9</group_length>
<Field_Character><name>v</name><field_number>1</field_number><field_location unit="byte">1</field_location>
<data_type>ASCII_Integer</data_type><field_length unit="byte">3</field_length></Field_Character>
</Group_Field_Character></Record_Character></Table_Character>""", records)
    s = parse_label(label)["structures"][0]
    assert [f["name"] for f in s["fields"]] == ["id", "group_1_v", "group_2_v", "group_3_v"]
    assert read_table_data(s) == [[1, 100, 200, 300], [2, 400, 500, 600]]


@pytest.mark.req("REQ-10")
def test_array_scaling_and_special_constants(tmp_path: Path) -> None:
    raw = np.array([[1, 2], [-32768, 4]], dtype=">i2")
    label = _write(tmp_path, """<Array_2D_Image><offset unit="byte">0</offset><axes>2</axes>
<axis_index_order>Last Index Fastest</axis_index_order>
<Element_Array><data_type>SignedMSB2</data_type><scaling_factor>0.5</scaling_factor><value_offset>10</value_offset>
</Element_Array>
<Axis_Array><axis_name>Line</axis_name><elements>2</elements><sequence_number>1</sequence_number></Axis_Array>
<Axis_Array><axis_name>Sample</axis_name><elements>2</elements><sequence_number>2</sequence_number></Axis_Array>
<Special_Constants><missing_constant>-32768</missing_constant></Special_Constants>
</Array_2D_Image>""", raw.tobytes())
    data = read_array_data(parse_label(label)["structures"][0])
    assert data[0, 0] == 10.5 and data[0, 1] == 11.0 and data[1, 1] == 12.0
    assert np.isnan(data[1, 0])


@pytest.mark.req("REQ-10", "REQ-11")
def test_radix_special_constant_for_float_array(tmp_path: Path) -> None:
    fill = np.array([0xFF7FFFFB], dtype=">u4").view(">f4")[0]
    raw = np.array([[1.5, fill]], dtype=">f4")
    label = _write(tmp_path, """<Array_2D_Image><offset unit="byte">0</offset><axes>2</axes>
<Element_Array><data_type>IEEE754MSBSingle</data_type></Element_Array>
<Axis_Array><axis_name>Line</axis_name><elements>1</elements><sequence_number>1</sequence_number></Axis_Array>
<Axis_Array><axis_name>Sample</axis_name><elements>2</elements><sequence_number>2</sequence_number></Axis_Array>
<Special_Constants><invalid_constant>16#FF7FFFFB#</invalid_constant></Special_Constants>
</Array_2D_Image>""", raw.tobytes())
    data = read_array_data(parse_label(label)["structures"][0])
    assert data[0, 0] == 1.5 and np.isnan(data[0, 1])


@pytest.mark.req("REQ-10", "REQ-04")
def test_table_field_scaling_and_missing_constant(tmp_path: Path) -> None:
    label = _write(tmp_path, """<Table_Delimited><offset unit="byte">0</offset><records>2</records>
<field_delimiter>Comma</field_delimiter><Record_Delimited><fields>1</fields><groups>0</groups>
<Field_Delimited><name>t</name><field_number>1</field_number><data_type>ASCII_Real</data_type>
<scaling_factor>2</scaling_factor><Special_Constants><missing_constant>-999</missing_constant></Special_Constants>
</Field_Delimited></Record_Delimited></Table_Delimited>""", b"1.5\r\n-999\r\n")
    assert read_table_data(parse_label(label)["structures"][0]) == [[3.0], [None]]


@pytest.mark.req("REQ-07", "BUG-07")
@pytest.mark.parametrize("band_axis_pos", [0, 2])
def test_3d_band_selection_by_axis_name(tmp_path: Path, band_axis_pos: int) -> None:
    names = ["Line", "Sample"]
    names.insert(band_axis_pos, "Band")
    shape_by_name = {"Band": 4, "Line": 2, "Sample": 3}
    dims = [shape_by_name[n] for n in names]
    cube = np.arange(np.prod(dims), dtype="u1").reshape(dims)
    axes = "".join(
        f"<Axis_Array><axis_name>{n}</axis_name><elements>{d}</elements>"
        f"<sequence_number>{i + 1}</sequence_number></Axis_Array>"
        for i, (n, d) in enumerate(zip(names, dims))
    )
    label = _write(tmp_path, f"""<Array_3D_Spectrum><offset unit="byte">0</offset><axes>3</axes>
<Element_Array><data_type>UnsignedByte</data_type></Element_Array>{axes}</Array_3D_Spectrum>""", cube.tobytes())
    s = parse_label(label)["structures"][0]
    assert s["band_axis"] == band_axis_pos
    assert array_plane_shape(s) == (2, 3)
    np.testing.assert_array_equal(read_array_data(s, band=3), np.take(cube, 3, axis=band_axis_pos))
    with pytest.raises(IndexError):
        read_array_data(s, band=4)


@pytest.mark.req("REQ-11")
def test_short_data_file_is_reported(tmp_path: Path) -> None:
    label = _write(tmp_path, """<Array_2D_Image><offset unit="byte">0</offset><axes>2</axes>
<Element_Array><data_type>UnsignedByte</data_type></Element_Array>
<Axis_Array><axis_name>Line</axis_name><elements>10</elements><sequence_number>1</sequence_number></Axis_Array>
<Axis_Array><axis_name>Sample</axis_name><elements>10</elements><sequence_number>2</sequence_number></Axis_Array>
</Array_2D_Image>""", b"\x00" * 50)
    with pytest.raises(ValueError, match="shorter"):
        read_array_data(parse_label(label)["structures"][0])


@pytest.mark.req("REQ-14")
def test_xml_external_entities_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    label = tmp_path / "x.xml"
    label.write_text(f"""<?xml version="1.0"?><!DOCTYPE r [<!ENTITY s SYSTEM "file://{secret}">]>
<Product_Observational {NS}><Identification_Area><title>&s;</title></Identification_Area></Product_Observational>""")
    parsed = parse_label(label)
    assert "TOP-SECRET" not in str(parsed["xml_tree"])
