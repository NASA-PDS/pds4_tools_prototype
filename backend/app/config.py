"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


# Shared working directory for parsed-label records and uploaded files. Point every
# worker/replica at the same directory (e.g. a mounted volume) to share state.
CACHE_DIR = Path(os.environ.get("PDS_CACHE_DIR") or Path(tempfile.gettempdir()) / "pds4_viewer")
LABEL_DIR = CACHE_DIR / "labels"
UPLOAD_DIR = CACHE_DIR / "uploads"

# Labels and uploads not accessed for this long are deleted (sliding expiration).
CACHE_TTL_SECONDS = _int_env("PDS_CACHE_TTL_SECONDS", 24 * 3600)

# In-process LRU cache for decoded arrays / table rows, per worker.
DATA_CACHE_BYTES = _int_env("PDS_DATA_CACHE_MB", 512) * 1024 * 1024

# Max points sent to the browser for line/scatter plots (evenly decimated beyond this).
PLOT_MAX_POINTS = _int_env("PDS_PLOT_MAX_POINTS", 50_000)

# Max bytes accepted per uploaded file.
MAX_UPLOAD_BYTES = _int_env("PDS_MAX_UPLOAD_MB", 1024) * 1024 * 1024
