"""Pluggable storage backends for browsing and reading PDS4 products.

Every read in the application goes through a backend, so data never has to be
copied to local disk first. Backends support ranged reads, which lets the
parser fetch only the bytes a request needs (one image band, one page of a
table) — essential for large products in S3.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol, runtime_checkable


@dataclass
class FileEntry:
    """A single file or directory entry returned by a storage backend."""

    name: str
    path: str
    is_dir: bool
    size: int | None = None
    is_label: bool = False


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for storage backends that can browse and read files."""

    def list_directory(self, path: str) -> list[FileEntry]:
        """List files and directories at the given path."""
        ...

    def read_file(self, path: str) -> bytes:
        """Read the full contents of a file (use for small files such as labels)."""
        ...

    def read_range(self, path: str, offset: int, length: int) -> bytes:
        """Read `length` bytes starting at byte `offset`. May return fewer bytes at EOF."""
        ...

    def open_stream(self, path: str, offset: int = 0) -> IO[bytes]:
        """Open a binary stream positioned at `offset` (for sequential reads)."""
        ...

    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        ...

    def get_parent(self, path: str) -> str | None:
        """Return the parent path, or None if at root."""
        ...

    def join(self, directory: str, name: str) -> str:
        """Join a directory path and a file name in this backend's path syntax."""
        ...

    @property
    def root(self) -> str:
        """Return the root path for this backend."""
        ...


LABEL_EXTS = {".xml", ".lblx"}


class LocalFilesystemBackend:
    """Browse and read files under a fixed root directory on the local filesystem.

    All paths are resolved and confined to the root; anything outside it is
    reported as not found.
    """

    def __init__(self, root_path: str | Path) -> None:
        self._root = Path(root_path).resolve()

    @property
    def root(self) -> str:
        return str(self._root)

    def _resolve(self, path: str) -> Path:
        """Resolve a path and refuse anything outside the configured root.

        Out-of-root paths raise FileNotFoundError so callers return 404 without
        revealing whether the path exists.
        """
        target = (Path(path) if path else self._root).resolve()
        if target != self._root and self._root not in target.parents:
            raise FileNotFoundError(f"Path not found: {path}")
        return target

    def list_directory(self, path: str) -> list[FileEntry]:
        target = self._resolve(path)
        if not target.is_dir():
            raise FileNotFoundError(f"Directory not found: {path}")

        entries: list[FileEntry] = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name.startswith("."):
                    continue
                try:
                    is_dir = item.is_dir()
                    size = item.stat().st_size if not is_dir else None
                    is_label = not is_dir and item.suffix.lower() in LABEL_EXTS
                    entries.append(FileEntry(name=item.name, path=str(item), is_dir=is_dir,
                                             size=size, is_label=is_label))
                except PermissionError:
                    continue
        except PermissionError:
            raise PermissionError(f"Access denied: {path}")

        return entries

    def _file(self, path: str) -> Path:
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return target

    def read_file(self, path: str) -> bytes:
        return self._file(path).read_bytes()

    def read_range(self, path: str, offset: int, length: int) -> bytes:
        with open(self._file(path), "rb") as f:
            f.seek(offset)
            return f.read(length)

    def open_stream(self, path: str, offset: int = 0) -> IO[bytes]:
        f = open(self._file(path), "rb")
        f.seek(offset)
        return f

    def file_exists(self, path: str) -> bool:
        try:
            return self._resolve(path).is_file()
        except FileNotFoundError:
            return False

    def get_parent(self, path: str) -> str | None:
        try:
            target = self._resolve(path)
        except FileNotFoundError:
            return None
        if target == self._root:
            return None
        return str(target.parent)

    def join(self, directory: str, name: str) -> str:
        return str(Path(directory) / name)


class S3StorageBackend:
    """Browse and read objects in an S3 bucket using ranged GETs (no full downloads)."""

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None,
                 aws_access_key_id: str | None = None, aws_secret_access_key: str | None = None,
                 client: object | None = None) -> None:
        if client is None:
            try:
                import boto3
            except ImportError:
                raise ImportError("boto3 is required for the S3 backend. Install with: pip install '.[s3]'")

            session_kwargs: dict[str, str] = {}
            if region:
                session_kwargs["region_name"] = region
            if aws_access_key_id:
                session_kwargs["aws_access_key_id"] = aws_access_key_id
            if aws_secret_access_key:
                session_kwargs["aws_secret_access_key"] = aws_secret_access_key
            client = boto3.client("s3", **session_kwargs)

        self._s3 = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    @property
    def root(self) -> str:
        return f"s3://{self._bucket}/{self._prefix}" if self._prefix else f"s3://{self._bucket}"

    def _normalize_key(self, path: str) -> str:
        """Convert a display path to an S3 key, confined to the configured prefix."""
        if not path:
            return self._prefix
        if path.startswith(f"s3://{self._bucket}"):
            path = path[len(f"s3://{self._bucket}"):]
        key = path.strip("/")
        parts = key.split("/") if key else []
        if any(p in ("..", ".") for p in parts):
            raise FileNotFoundError(f"Path not found: {path}")
        if self._prefix and key != self._prefix and not key.startswith(self._prefix + "/"):
            raise FileNotFoundError(f"Path not found: {path}")
        return key

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}" if key else f"s3://{self._bucket}"

    def list_directory(self, path: str) -> list[FileEntry]:
        prefix = self._normalize_key(path)
        if prefix:
            prefix = prefix.rstrip("/") + "/"

        dirs: list[FileEntry] = []
        files: list[FileEntry] = []
        paginator = self._s3.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                dir_key = cp["Prefix"].rstrip("/")
                if dir_key.split("/")[-1].startswith("."):
                    continue  # hidden, same as the local backend
                dirs.append(FileEntry(name=dir_key.split("/")[-1], path=self._uri(dir_key), is_dir=True))
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix:
                    continue
                name = key.split("/")[-1]
                if name.startswith("."):
                    continue  # hidden, same as the local backend
                suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                files.append(FileEntry(name=name, path=self._uri(key), is_dir=False,
                                       size=obj.get("Size"), is_label=suffix in LABEL_EXTS))

        dirs.sort(key=lambda e: e.name.lower())
        files.sort(key=lambda e: e.name.lower())
        return dirs + files

    def _get(self, path: str, byte_range: str | None = None) -> dict:
        from botocore.exceptions import ClientError

        key = self._normalize_key(path)
        kwargs = {"Bucket": self._bucket, "Key": key}
        if byte_range:
            kwargs["Range"] = byte_range
        try:
            return self._s3.get_object(**kwargs)  # type: ignore[attr-defined]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"File not found: {path}") from e
            if code == "InvalidRange":
                return {"Body": io.BytesIO(b"")}
            raise

    def read_file(self, path: str) -> bytes:
        return self._get(path)["Body"].read()

    def read_range(self, path: str, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""
        return self._get(path, f"bytes={offset}-{offset + length - 1}")["Body"].read()

    def open_stream(self, path: str, offset: int = 0) -> IO[bytes]:
        """Sequential reader made of bounded ranged GETs (STREAM_CHUNK_BYTES each).

        Nothing past the last chunk the caller actually consumes is requested.
        """
        self._normalize_key(path)  # fail fast on paths outside the prefix
        return io.BufferedReader(_RangedChunkReader(self, path, offset), buffer_size=STREAM_CHUNK_BYTES)

    def file_exists(self, path: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            key = self._normalize_key(path)
            self._s3.head_object(Bucket=self._bucket, Key=key)  # type: ignore[attr-defined]
            return True
        except FileNotFoundError:
            return False
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def get_parent(self, path: str) -> str | None:
        try:
            key = self._normalize_key(path)
        except FileNotFoundError:
            return None
        if key == self._prefix or "/" not in key:
            return None
        return self._uri(key.rsplit("/", 1)[0])

    def join(self, directory: str, name: str) -> str:
        return directory.rstrip("/") + "/" + name


STREAM_CHUNK_BYTES = 1024 * 1024


class _RangedChunkReader(io.RawIOBase):
    """Raw stream that fetches an S3 object in bounded `bytes=a-b` ranges on demand."""

    def __init__(self, backend: S3StorageBackend, path: str, offset: int) -> None:
        self._backend = backend
        self._path = path
        self._pos = offset
        self._buf = b""
        self._eof = False

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        if not self._buf and not self._eof:
            self._buf = self._backend.read_range(self._path, self._pos, STREAM_CHUNK_BYTES)
            self._pos += len(self._buf)
            self._eof = len(self._buf) < STREAM_CHUNK_BYTES
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

# Backends whose names start with "_" are internal (e.g. "_uploads") and are not
# advertised to the browse UI.
UPLOADS_BACKEND = "_uploads"

_storage_backends: dict[str, StorageBackend] = {}


def register_backend(name: str, backend: StorageBackend) -> None:
    _storage_backends[name] = backend


def get_backend(name: str) -> StorageBackend | None:
    return _storage_backends.get(name)


def list_backends() -> list[dict[str, str]]:
    return [{"name": name, "root": b.root} for name, b in _storage_backends.items() if not name.startswith("_")]


DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parents[3] / "test_data"


def init_default_backends(uploads_dir: Path) -> None:
    """Initialize storage backends from environment variables.

    PDS_LOCAL_ROOT: directory to expose for browsing. Defaults to the repo's
        bundled test_data directory (never the user's home directory).
    PDS_S3_BUCKET / PDS_S3_PREFIX / PDS_S3_REGION: optional S3 source. Credentials
        come from the standard AWS chain (instance role, env, profile) unless
        PDS_S3_ACCESS_KEY_ID / PDS_S3_SECRET_ACCESS_KEY are set.
    """
    register_backend(UPLOADS_BACKEND, LocalFilesystemBackend(uploads_dir))

    local_root = os.environ.get("PDS_LOCAL_ROOT")
    if local_root:
        register_backend("local", LocalFilesystemBackend(local_root))
    elif DEFAULT_LOCAL_ROOT.is_dir():
        register_backend("local", LocalFilesystemBackend(DEFAULT_LOCAL_ROOT))

    s3_bucket = os.environ.get("PDS_S3_BUCKET")
    if s3_bucket:
        register_backend("s3", S3StorageBackend(
            bucket=s3_bucket,
            prefix=os.environ.get("PDS_S3_PREFIX", ""),
            region=os.environ.get("PDS_S3_REGION"),
            aws_access_key_id=os.environ.get("PDS_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("PDS_S3_SECRET_ACCESS_KEY"),
        ))
