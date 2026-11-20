"""Per-process LRU cache for decoded data, bounded by approximate byte size.

Decoding an image or a whole table is the expensive part of most requests;
caching it means pan/zoom re-renders, pixel lookups, statistics and repeated
plots don't re-read the file.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

import numpy as np

from app import config

T = TypeVar("T")


def estimate_size(value: Any) -> int:
    if isinstance(value, np.ndarray):
        return value.nbytes
    if isinstance(value, list):
        if not value:
            return 64
        width = len(value[0]) if isinstance(value[0], list) else 1
        return 64 + len(value) * (56 + width * 32)
    return 1024


class DataCache:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[Hashable, tuple[int, Any]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get_or_load(self, key: Hashable, loader: Callable[[], T]) -> T:
        with self._lock:
            hit = self._items.get(key)
            if hit is not None:
                self._items.move_to_end(key)
                return hit[1]
        value = loader()
        size = estimate_size(value)
        if size <= self.max_bytes:
            with self._lock:
                if key not in self._items:
                    self._items[key] = (size, value)
                    self._bytes += size
                while self._bytes > self.max_bytes and self._items:
                    _, (evicted, _) = self._items.popitem(last=False)
                    self._bytes -= evicted
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)


data_cache = DataCache(config.DATA_CACHE_BYTES)
