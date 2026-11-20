"""Disk-backed store for parsed label records.

Records are JSON files in a shared directory, so they survive restarts and are
visible to every worker process (and every replica, if the directory is a
shared volume). Records and upload sessions expire after a period of inactivity.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CLEANUP_INTERVAL_SECONDS = 600
_MEMO_SIZE = 64


class LabelStore:
    def __init__(self, label_dir: Path, upload_dir: Path, ttl_seconds: int) -> None:
        self.label_dir = label_dir
        self.upload_dir = upload_dir
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._memo: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._last_cleanup = 0.0
        self.label_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, label_id: str) -> Path | None:
        if not _ID_RE.match(label_id):
            return None
        return self.label_dir / f"{label_id}.json"

    def put(self, record: dict[str, Any]) -> str:
        label_id = uuid.uuid4().hex
        # The file name is a server-generated UUID; nothing from the request is used in it.
        path = os.path.join(self.label_dir, f"{label_id}.json")
        fd, tmp = tempfile.mkstemp(dir=self.label_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(record, f)
            os.replace(tmp, path)  # atomic: readers never see a partial file
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        self.maybe_cleanup()
        return label_id

    def get(self, label_id: str) -> dict[str, Any] | None:
        path = self._path(label_id)
        if path is None:
            return None
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            with self._lock:
                self._memo.pop(label_id, None)
            return None

        now = time.time()
        if now - mtime > self.ttl_seconds:
            return None

        with self._lock:
            cached = self._memo.get(label_id)
        if cached is not None:
            record = cached[1]
        else:
            try:
                record = json.loads(path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                return None
            with self._lock:
                self._memo[label_id] = (mtime, record)
                while len(self._memo) > _MEMO_SIZE:
                    self._memo.popitem(last=False)

        # Sliding expiration: refresh the record and its upload session (at most once a minute).
        if now - mtime > 60:
            _touch(path)
            session = record.get("upload_session")
            if session:
                _touch(self.upload_dir / session)
        return record

    def list(self) -> list[dict[str, str]]:
        out = []
        for path in sorted(self.label_dir.glob("*.json")):
            record = self.get(path.stem)
            if record:
                out.append({"label_id": path.stem, "filename": record["filename"]})
        return out

    def clear(self) -> None:
        with self._lock:
            self._memo.clear()
        for path in self.label_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def new_upload_session(self) -> Path:
        session = self.upload_dir / f"session_{uuid.uuid4().hex}"
        session.mkdir(parents=True)
        return session

    def maybe_cleanup(self) -> None:
        now = time.time()
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = now
        threading.Thread(target=self.cleanup, daemon=True).start()

    def cleanup(self, now: float | None = None) -> int:
        """Delete expired label records and upload sessions. Returns the number removed."""
        now = now or time.time()
        cutoff = now - self.ttl_seconds
        removed = 0
        for path in self.label_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    with self._lock:
                        self._memo.pop(path.stem, None)
                    removed += 1
            except FileNotFoundError:
                continue
        for session in self.upload_dir.glob("session_*"):
            try:
                if session.stat().st_mtime < cutoff:
                    shutil.rmtree(session, ignore_errors=True)
                    removed += 1
            except FileNotFoundError:
                continue
        return removed


def _touch(path: Path) -> None:
    try:
        os.utime(path)
    except OSError:
        pass
