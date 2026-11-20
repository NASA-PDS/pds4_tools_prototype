"""Label upload and metadata endpoints."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import config
from app.api.deps import Label, label_store, list_labels, store_label
from app.models.schemas import LabelMetadata, LabelUploadResponse, StructureSummary
from app.services.label_parser import parse_label
from app.services.storage import UPLOADS_BACKEND

router = APIRouter()

UPLOAD_DIR = config.UPLOAD_DIR
LABEL_SUFFIXES = {".xml": ".xml", ".lblx": ".lblx"}


def _session_path(session_dir: Path, name: str) -> Path:
    """Return the path for an uploaded file inside the session dir.

    Directory components are stripped, and the resolved path is checked to be
    inside the session dir so an upload can never be written or read elsewhere.
    """
    base = os.path.basename(name.replace("\\", "/"))
    if base in ("", ".", ".."):
        raise HTTPException(status_code=400, detail=f"Invalid filename: {name!r}")
    root = os.path.realpath(session_dir)
    candidate = os.path.realpath(os.path.join(root, base))
    if os.path.commonpath([root, candidate]) != root:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {name!r}")
    return Path(candidate)


def _save_upload(upload: UploadFile, dest: Path) -> None:
    written = 0
    with open(dest, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > config.MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the upload size limit")
            f.write(chunk)


def summarize(parsed: dict) -> list[StructureSummary]:
    return [
        StructureSummary(
            index=s["index"],
            name=s["name"],
            local_identifier=s.get("local_identifier"),
            structure_type=s["structure_type"],
            record_count=s.get("record_count"),
            field_count=s.get("field_count"),
            dimensions=s.get("dimensions"),
        )
        for s in parsed["structures"]
    ]


@router.post("/upload", response_model=LabelUploadResponse)
def upload_label(
    label_file: UploadFile,
    data_files: list[UploadFile] = File(default_factory=list),
) -> LabelUploadResponse:
    """Upload a PDS4 label file (XML/LBLX) and its associated data files.

    Data files are matched to the label's <File><file_name> entries by name.
    Uploads live in a per-upload session directory that expires with the label.
    """
    if not label_file.filename:
        raise HTTPException(status_code=400, detail="No label file provided")
    suffix = LABEL_SUFFIXES.get(Path(label_file.filename).suffix.lower())
    if suffix is None:
        raise HTTPException(status_code=400, detail="Label file must be .xml or .lblx")

    session_dir = label_store.new_upload_session()
    try:
        # The label is stored under a server-generated name; only data files keep the
        # names the label refers to them by.
        label_path = session_dir / f"_label_{uuid.uuid4().hex}{suffix}"
        _save_upload(label_file, label_path)
        for df in data_files:
            if df.filename:
                _save_upload(df, _session_path(session_dir, df.filename))

        try:
            parsed = parse_label(label_path, content=label_path.read_bytes(), source=UPLOADS_BACKEND)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to parse label: {e}")
    except HTTPException:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise

    parsed["upload_session"] = session_dir.name
    parsed["filename"] = os.path.basename(label_file.filename.replace("\\", "/"))
    label_id = store_label(parsed)
    return LabelUploadResponse(label_id=label_id, filename=parsed["filename"], structures=summarize(parsed))


@router.get("", response_model=list[dict[str, str]])
def get_labels() -> list[dict[str, str]]:
    """List all stored labels."""
    return list_labels()


@router.get("/{label_id}", response_model=LabelMetadata)
def get_label_detail(label_id: str, label: Label) -> LabelMetadata:
    """Get label metadata including the XML tree."""
    return LabelMetadata(label_id=label_id, filename=label["filename"], xml_tree=label["xml_tree"])


@router.get("/{label_id}/structures", response_model=list[StructureSummary])
def get_structures(label_id: str, label: Label) -> list[StructureSummary]:
    """List all data structures in a label."""
    return summarize(label)
