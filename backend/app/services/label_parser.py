"""PDS4 label parser and data readers.

Parses PDS4 XML/LBLX labels and extracts metadata about the data structures
they describe (tables, images, arrays). Data is read through a storage backend
with ranged reads, so only the bytes a request needs are fetched.

Supported:
  * Table_Character, Table_Binary, Table_Delimited (incl. nested/repeated groups)
  * Array_2D*, Array_3D* (band selection for 3D)
  * MSB and LSB numeric types
  * scaling_factor / value_offset and Special_Constants (mapped to null / NaN)
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import IO, Any

import numpy as np
from lxml import etree

PDS4_NS = "http://pds.nasa.gov/pds4/pds/v1"
NSMAP = {"pds": PDS4_NS}

TABLE_TYPES = {
    f"{{{PDS4_NS}}}Table_Character",
    f"{{{PDS4_NS}}}Table_Binary",
    f"{{{PDS4_NS}}}Table_Delimited",
}

ARRAY_TYPES = {
    f"{{{PDS4_NS}}}Array",
    f"{{{PDS4_NS}}}Array_2D",
    f"{{{PDS4_NS}}}Array_2D_Image",
    f"{{{PDS4_NS}}}Array_2D_Map",
    f"{{{PDS4_NS}}}Array_2D_Spectrum",
    f"{{{PDS4_NS}}}Array_3D",
    f"{{{PDS4_NS}}}Array_3D_Image",
    f"{{{PDS4_NS}}}Array_3D_Movie",
    f"{{{PDS4_NS}}}Array_3D_Spectrum",
}

DATA_STRUCTURE_TYPES = TABLE_TYPES | ARRAY_TYPES

PDS4_TO_NUMPY_DTYPE: dict[str, str] = {
    "ASCII_Real": "float64",
    "ASCII_Integer": "int64",
    "ASCII_NonNegative_Integer": "int64",
    "ASCII_String": "U",
    "ASCII_Date_Time_YMD": "U",
    "ASCII_Date_Time_YMD_UTC": "U",
    "ASCII_Date_Time_DOY": "U",
    "ASCII_Date_Time_DOY_UTC": "U",
    "ASCII_Date": "U",
    "ASCII_Date_YMD": "U",
    "ASCII_Date_DOY": "U",
    "ASCII_Time": "U",
    "ASCII_Boolean": "U",
    "ASCII_Numeric_Base2": "U",
    "ASCII_Numeric_Base8": "U",
    "ASCII_Numeric_Base16": "U",
    "ASCII_AnyURI": "U",
    "ASCII_DOI": "U",
    "ASCII_LID": "U",
    "ASCII_LIDVID": "U",
    "ASCII_LIDVID_LID": "U",
    "ASCII_MD5_Checksum": "U",
    "ASCII_VID": "U",
    "ASCII_Directory_Path_Name": "U",
    "ASCII_File_Name": "U",
    "ASCII_File_Specification_Name": "U",
    "ASCII_Short_String_Collapsed": "U",
    "ASCII_Short_String_Preserved": "U",
    "ASCII_Text_Collapsed": "U",
    "ASCII_Text_Preserved": "U",
    "UTF8_String": "U",
    "UTF8_Short_String_Collapsed": "U",
    "UTF8_Short_String_Preserved": "U",
    "UTF8_Text_Preserved": "U",
    "IEEE754MSBSingle": ">f4",
    "IEEE754MSBDouble": ">f8",
    "IEEE754LSBSingle": "<f4",
    "IEEE754LSBDouble": "<f8",
    "SignedMSB2": ">i2",
    "SignedMSB4": ">i4",
    "SignedMSB8": ">i8",
    "UnsignedMSB2": ">u2",
    "UnsignedMSB4": ">u4",
    "UnsignedMSB8": ">u8",
    "SignedLSB2": "<i2",
    "SignedLSB4": "<i4",
    "SignedLSB8": "<i8",
    "UnsignedLSB2": "<u2",
    "UnsignedLSB4": "<u4",
    "UnsignedLSB8": "<u8",
    "UnsignedByte": "u1",
    "SignedByte": "i1",
}

# Map PDS4 field_delimiter values to the actual character.
FIELD_DELIMITERS: dict[str, str] = {
    "comma": ",",
    "horizontal tab": "\t",
    "semicolon": ";",
    "vertical bar": "|",
}

SPECIAL_CONSTANT_TAGS = (
    "missing_constant",
    "invalid_constant",
    "unknown_constant",
    "not_applicable_constant",
    "saturated_constant",
    "high_instrument_saturation",
    "high_representation_saturation",
    "low_instrument_saturation",
    "low_representation_saturation",
    "error_constant",
)

# Hardened parser: no external entities, no DTD loading, no network access.
_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def _text(element: etree._Element, xpath: str) -> str | None:
    nodes = element.xpath(xpath, namespaces=NSMAP)
    if nodes and nodes[0].text is not None:
        return nodes[0].text.strip()
    return None


def _int(element: etree._Element, xpath: str) -> int | None:
    val = _text(element, xpath)
    return int(val) if val is not None else None


def _float(element: etree._Element, xpath: str) -> float | None:
    val = _text(element, xpath)
    return float(val) if val is not None else None


def _sibling(label_path: str, file_name: str) -> str:
    """Path of a data file that sits next to the label (local path or URI)."""
    if "://" in label_path:
        return label_path.rsplit("/", 1)[0] + "/" + file_name
    return str(Path(label_path).parent / file_name)


def _special_constants(element: etree._Element) -> list[str]:
    sc = element.xpath("pds:Special_Constants", namespaces=NSMAP)
    if not sc:
        return []
    values = []
    for tag in SPECIAL_CONSTANT_TAGS:
        v = _text(sc[0], f"pds:{tag}")
        if v is not None:
            values.append(v)
    return values


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------

def parse_label(
    xml_path: str | Path,
    content: bytes | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Parse a PDS4 XML label and return metadata about its structures.

    Args:
        xml_path: Path (or URI) of the label. Data files are resolved next to it.
        content: Label bytes, if already read; otherwise read from `xml_path` on local disk.
        source: Name of the storage backend data files should be read from. None means
            unrestricted local disk (library/test use only; the API always passes one).
    """
    xml_path = str(xml_path)
    if content is None:
        content = Path(xml_path).read_bytes()
    root = etree.fromstring(content, _XML_PARSER)

    structures: list[dict[str, Any]] = []
    file_areas = [
        child for child in root
        if isinstance(child.tag, str) and etree.QName(child.tag).localname.startswith("File_Area_")
    ]

    for file_area in file_areas:
        file_area_type = etree.QName(file_area.tag).localname
        is_supplemental = file_area_type != "File_Area_Observational"
        data_filename = _text(file_area, "pds:File/pds:file_name")
        data_path = _sibling(xml_path, data_filename) if data_filename else None

        for child in file_area:
            tag = child.tag
            if tag not in DATA_STRUCTURE_TYPES:
                continue

            idx = len(structures)
            local_tag = etree.QName(tag).localname
            name = _text(child, "pds:name") or _text(child, "pds:local_identifier") or f"{local_tag} #{idx}"

            structure: dict[str, Any] = {
                "index": idx,
                "name": name,
                "local_identifier": _text(child, "pds:local_identifier"),
                "structure_type": local_tag,
                "source": source,
                "data_file": data_path,
                "offset": _int(child, "pds:offset") or 0,
                "supplemental": is_supplemental,
            }

            if tag in TABLE_TYPES:
                structure.update(_parse_table_structure(child, local_tag))
            else:
                structure.update(_parse_array_structure(child))

            structures.append(structure)

    required_data_files: list[str] = []
    for s in structures:
        if s.get("supplemental") or not s.get("data_file"):
            continue
        fname = s["data_file"].rsplit("/", 1)[-1]
        if fname not in required_data_files:
            required_data_files.append(fname)

    return {
        "filename": xml_path.rsplit("/", 1)[-1],
        "xml_path": xml_path,
        "structures": structures,
        "xml_tree": _element_to_dict(root),
        "referenced_data_files": required_data_files,
    }


def _parse_table_structure(element: etree._Element, table_type: str) -> dict[str, Any]:
    """Extract table-specific metadata: fields, record count, record length."""
    kind = {"Table_Character": "Character", "Table_Binary": "Binary"}.get(table_type, "Delimited")
    record_elem = element.xpath(f"pds:Record_{kind}", namespaces=NSMAP)

    fields: list[dict[str, Any]] = []
    record_length = None
    if record_elem:
        record_length = _int(record_elem[0], "pds:record_length")
        _extract_fields(record_elem[0], f"Field_{kind}", f"Group_Field_{kind}", fields)

    return {
        "record_count": _int(element, "pds:records"),
        "record_length": record_length,
        "field_count": len(fields),
        "fields": fields,
        "field_delimiter": _text(element, "pds:field_delimiter"),
    }


def _extract_fields(
    parent: etree._Element,
    field_tag: str,
    group_tag: str,
    fields: list[dict[str, Any]],
    prefix: str = "",
    base: int = 0,
) -> None:
    """Recursively extract field definitions, expanding repeated groups.

    `base` is the 0-based byte offset of `parent` within the record. Field and
    group locations in PDS4 are 1-based and relative to their enclosing group,
    so each repetition of a group is shifted by group_length / repetitions.
    Stored field_location values are absolute (1-based, relative to the record).
    """
    for child in parent:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child.tag).localname
        if local == field_tag:
            field_num = _int(child, "pds:field_number") or (len(fields) + 1)
            name = _text(child, "pds:name") or f"field_{field_num}"
            rel_location = _int(child, "pds:field_location")
            fields.append({
                "name": f"{prefix}{name}",
                "field_number": len(fields) + 1,
                "data_type": _text(child, "pds:data_type") or "ASCII_String",
                "unit": _text(child, "pds:unit"),
                "description": _text(child, "pds:description"),
                "field_length": _int(child, "pds:field_length"),
                "field_location": base + rel_location if rel_location is not None else None,
                "scaling_factor": _float(child, "pds:scaling_factor"),
                "value_offset": _float(child, "pds:value_offset"),
                "special_constants": _special_constants(child),
            })
        elif local == group_tag:
            group_name = _text(child, "pds:name") or "group"
            repetitions = _int(child, "pds:repetitions") or 1
            group_location = _int(child, "pds:group_location")
            group_length = _int(child, "pds:group_length")
            group_start = base + group_location - 1 if group_location is not None else base
            rep_length = group_length // repetitions if group_length else 0
            for i in range(repetitions):
                group_prefix = f"{prefix}{group_name}_{i + 1}_" if repetitions > 1 else f"{prefix}{group_name}_"
                _extract_fields(child, field_tag, group_tag, fields, group_prefix, group_start + i * rep_length)


def _parse_array_structure(element: etree._Element) -> dict[str, Any]:
    """Extract array-specific metadata: dimensions, data type, scaling, band axis."""
    axis_data = []
    for axis in element.xpath("pds:Axis_Array", namespaces=NSMAP):
        seq = _int(axis, "pds:sequence_number") or 0
        axis_data.append((seq, _int(axis, "pds:elements") or 0, _text(axis, "pds:axis_name") or f"axis_{seq}"))
    axis_data.sort(key=lambda x: x[0])
    dimensions = [a[1] for a in axis_data]
    axis_names = [a[2] for a in axis_data]

    band_axis = None
    if len(dimensions) == 3:
        band_axis = next((i for i, n in enumerate(axis_names) if "band" in n.lower()), 0)

    element_array = element.xpath("pds:Element_Array", namespaces=NSMAP)
    ea = element_array[0] if element_array else element

    return {
        "axes": _int(element, "pds:axes"),
        "dimensions": dimensions,
        "axis_names": axis_names,
        "axis_index_order": _text(element, "pds:axis_index_order") or "Last Index Fastest",
        "band_axis": band_axis,
        "element_data_type": _text(ea, "pds:data_type"),
        "scaling_factor": _float(ea, "pds:scaling_factor"),
        "value_offset": _float(ea, "pds:value_offset"),
        "special_constants": _special_constants(element),
    }


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

class _UnrestrictedLocal:
    """Reader for structures parsed without a storage backend (library/test use)."""

    def file_exists(self, path: str) -> bool:
        return Path(path).is_file()

    def read_range(self, path: str, offset: int, length: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    def open_stream(self, path: str, offset: int = 0) -> IO[bytes]:
        f = open(path, "rb")
        f.seek(offset)
        return f


def _reader(structure: dict[str, Any]) -> tuple[Any, str]:
    from app.services.storage import get_backend

    data_file = structure.get("data_file")
    source = structure.get("source")
    backend: Any = get_backend(source) if source else _UnrestrictedLocal()
    if not data_file or backend is None or not backend.file_exists(data_file):
        name = data_file.rsplit("/", 1)[-1] if data_file else None
        raise FileNotFoundError(f"Data file not found: {name}")
    return backend, data_file


def _parse_constant(text: str, dtype: np.dtype | None = None) -> float | int:
    """Parse a special constant: decimal, or PDS4 radix form like 16#FF7FFFFB#."""
    m = re.fullmatch(r"\s*(\d+)#([0-9A-Fa-f]+)#\s*", text)
    if m:
        bits = int(m.group(2), int(m.group(1)))
        if dtype is not None and dtype.kind in "fi":
            raw = np.array(bits, dtype=np.dtype(f"{dtype.byteorder}u{dtype.itemsize}"))
            return raw.view(dtype)[()].item()
        return bits
    return float(text)


# ---- Tables ---------------------------------------------------------------

def read_table_data(
    structure: dict[str, Any],
    offset: int = 0,
    limit: int | None = None,
) -> list[list[Any]]:
    """Read rows [offset, offset+limit) from a table.

    Rows are lists of values in field order (positional, so duplicate column
    names are supported). Special constants become None; scaling is applied.
    """
    backend, path = _reader(structure)

    record_count = structure.get("record_count") or 0
    end = record_count if limit is None else min(offset + limit, record_count)
    if offset >= end:
        return []

    table_type = structure["structure_type"]
    fields = structure.get("fields", [])
    file_offset = structure.get("offset", 0)

    if table_type in ("Table_Character", "Table_Binary"):
        record_length = structure.get("record_length")
        if not record_length:
            raise ValueError("Fixed-width table has no record_length")
        blob = backend.read_range(path, file_offset + offset * record_length, (end - offset) * record_length)
        decode = _decode_character_field if table_type == "Table_Character" else _decode_binary_field
        rows = []
        for r in range(len(blob) // record_length):
            record = blob[r * record_length:(r + 1) * record_length]
            rows.append([_postprocess(decode(record, f), f) for f in fields])
        return rows

    delimiter = FIELD_DELIMITERS.get((structure.get("field_delimiter") or "comma").lower(), ",")
    return _read_delimited_table(backend, path, fields, file_offset, offset, end, delimiter)


def _decode_character_field(record: bytes, field: dict[str, Any]) -> Any:
    loc = (field.get("field_location") or 1) - 1
    length = field.get("field_length") or 0
    raw = record[loc:loc + length].decode("utf-8", errors="replace").strip()
    return _coerce_value(raw, field.get("data_type", "ASCII_String"))


def _decode_binary_field(record: bytes, field: dict[str, Any]) -> Any:
    loc = (field.get("field_location") or 1) - 1
    dt = field.get("data_type", "UnsignedByte")
    np_type = PDS4_TO_NUMPY_DTYPE.get(dt)
    if np_type is None or np_type == "U" or np_type in ("float64", "int64"):
        # Character field embedded in a binary record
        return _decode_character_field(record, field)
    return np.frombuffer(record, dtype=np.dtype(np_type), count=1, offset=loc)[0].item()


def _read_delimited_table(
    backend: Any,
    path: str,
    fields: list[dict[str, Any]],
    file_offset: int,
    start: int,
    end: int,
    delimiter: str = ",",
) -> list[list[Any]]:
    """Stream delimited records, honoring the label's field_delimiter and quoting."""
    rows: list[list[Any]] = []
    with backend.open_stream(path, file_offset) as raw:
        text = io.TextIOWrapper(io.BufferedReader(raw) if not hasattr(raw, "peek") else raw,
                                encoding="utf-8", errors="replace", newline="")
        for i, values in enumerate(csv.reader(text, delimiter=delimiter)):
            if i < start:
                continue
            if i >= end:
                break
            row: list[Any] = []
            for j, field in enumerate(fields):
                raw_val = values[j].strip() if j < len(values) else ""
                row.append(_postprocess(_coerce_value(raw_val, field.get("data_type", "ASCII_String")), field))
            rows.append(row)
    return rows


def _postprocess(value: Any, field: dict[str, Any]) -> Any:
    """Map special constants to None and apply scaling_factor / value_offset."""
    if value is None:
        return None
    constants = field.get("special_constants") or []
    if constants and isinstance(value, (int, float)):
        np_type = PDS4_TO_NUMPY_DTYPE.get(field.get("data_type", ""))
        dtype = np.dtype(np_type) if np_type and np_type != "U" else None
        for c in constants:
            try:
                if value == _parse_constant(c, dtype):
                    return None
            except ValueError:
                continue
    elif constants and isinstance(value, str) and value in constants:
        return None

    scale = field.get("scaling_factor")
    shift = field.get("value_offset")
    if isinstance(value, (int, float)) and (scale is not None or shift is not None):
        return value * (scale if scale is not None else 1.0) + (shift or 0.0)
    return value


def _coerce_value(raw: str, data_type: str) -> int | float | str | None:
    """Coerce a raw string value to its appropriate Python type."""
    if not raw or raw.lower() in ("n/a", "null", "nan"):
        return None
    try:
        if "Real" in data_type or "Double" in data_type or "Single" in data_type:
            return float(raw)
        if "Integer" in data_type:
            return int(raw)
    except (ValueError, TypeError):
        pass
    return raw


# ---- Arrays ---------------------------------------------------------------

def array_plane_shape(structure: dict[str, Any]) -> tuple[int, int]:
    """(height, width) of the 2D plane displayed for an array (band axis removed)."""
    dims = list(structure.get("dimensions") or [])
    if len(dims) == 3:
        dims.pop(structure.get("band_axis") or 0)
    if len(dims) >= 2:
        return dims[0], dims[1]
    return 1, dims[0] if dims else 0


def array_band_count(structure: dict[str, Any]) -> int:
    dims = structure.get("dimensions") or []
    if len(dims) == 3:
        return dims[structure.get("band_axis") or 0]
    return 1


def read_array_data(structure: dict[str, Any], band: int | None = None) -> np.ndarray:
    """Read array data, returning one 2D plane for 3D arrays (selected by `band`).

    When the band axis is the slowest-varying axis, only that band's bytes are read.
    Special constants become NaN and scaling is applied (result is then float64).
    """
    backend, path = _reader(structure)

    dims = list(structure.get("dimensions") or [])
    element_type = structure.get("element_data_type")
    np_type = PDS4_TO_NUMPY_DTYPE.get(element_type or "")
    if np_type is None or np_type == "U" or np_type in ("float64", "int64") and element_type.startswith("ASCII"):
        raise ValueError(f"Unsupported array data_type: {element_type}")
    if structure.get("axis_index_order", "Last Index Fastest") != "Last Index Fastest":
        raise ValueError(f"Unsupported axis_index_order: {structure.get('axis_index_order')}")

    dt = np.dtype(np_type)
    file_offset = structure.get("offset", 0)

    if len(dims) == 3:
        band_axis = structure.get("band_axis") or 0
        b = band or 0
        if not 0 <= b < dims[band_axis]:
            raise IndexError(f"Band {b} out of range (0-{dims[band_axis] - 1})")
        if band_axis == 0:
            plane_shape = dims[1:]
            plane = plane_shape[0] * plane_shape[1]
            data = _read_exact(backend, path, file_offset + b * plane * dt.itemsize, plane, dt).reshape(plane_shape)
        else:
            total = dims[0] * dims[1] * dims[2]
            data = np.take(_read_exact(backend, path, file_offset, total, dt).reshape(dims), b, axis=band_axis)
    else:
        total = int(np.prod(dims)) if dims else 0
        data = _read_exact(backend, path, file_offset, total, dt).reshape(dims)

    return _apply_array_scaling(data, structure)


def _read_exact(backend: Any, path: str, offset: int, count: int, dt: np.dtype) -> np.ndarray:
    blob = backend.read_range(path, offset, count * dt.itemsize)
    if len(blob) < count * dt.itemsize:
        raise ValueError(
            f"Data file is shorter than the label declares ({len(blob)} of {count * dt.itemsize} bytes)"
        )
    return np.frombuffer(blob, dtype=dt, count=count)


def _apply_array_scaling(data: np.ndarray, structure: dict[str, Any]) -> np.ndarray:
    constants = structure.get("special_constants") or []
    scale = structure.get("scaling_factor")
    shift = structure.get("value_offset")
    if not constants and scale is None and shift is None:
        return data

    out = data.astype(np.float64)
    if constants:
        values = []
        for c in constants:
            try:
                values.append(_parse_constant(c, data.dtype))
            except ValueError:
                continue
        if values:
            out[np.isin(data, np.array(values, dtype=data.dtype))] = np.nan
    if scale is not None:
        out *= scale
    if shift is not None:
        out += shift
    return out


# ---------------------------------------------------------------------------
# XML tree for the label explorer
# ---------------------------------------------------------------------------

_NS_PREFIXES: dict[str, str] = {
    "http://www.w3.org/2001/XMLSchema-instance": "xsi",
    "http://www.w3.org/2001/XMLSchema": "xs",
    PDS4_NS: "pds",
}


def _clean_attr_name(name: str) -> str:
    """Convert Clark notation {uri}local to prefix:local."""
    if name.startswith("{"):
        uri, local = name[1:].split("}", 1)
        prefix = _NS_PREFIXES.get(uri)
        return f"{prefix}:{local}" if prefix else local
    return name


def _element_to_dict(element: etree._Element) -> dict[str, Any]:
    """Convert an lxml element tree to a nested dict for JSON serialization."""
    tag = etree.QName(element.tag).localname
    result: dict[str, Any] = {"tag": tag}

    if element.attrib:
        result["attributes"] = {_clean_attr_name(k): v for k, v in element.attrib.items()}

    children = [c for c in element if isinstance(c.tag, str)]  # skip comments / PIs
    if children:
        result["children"] = [_element_to_dict(c) for c in children]
    elif element.text and element.text.strip():
        result["text"] = element.text.strip()

    return result
