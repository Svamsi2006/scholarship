"""Disk cache for search results and fetched page text.

Keys are SHA256 hashes of normalized input; files stored in .cache directory.
Disabled when CACHE=0.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

CACHE_DIR: Path = BASE_DIR / ".cache"
CACHE_ENABLED: bool = os.getenv("CACHE", "1") != "0"


def _ensure_dir() -> None:
    if CACHE_ENABLED and not CACHE_DIR.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(namespace: str, key: str) -> Path:
    normalized = f"{namespace}:{key.strip().lower()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def get_cache(namespace: str, key: str) -> Any | None:
    """Retrieve an item from cache if exists and not expired."""
    if not CACHE_ENABLED:
        return None
    path = _cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() > data.get("expires_at", 0):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return data.get("value")
    except Exception:
        return None


def set_cache(namespace: str, key: str, value: Any, ttl_seconds: int = 86400) -> None:
    """Save an item to disk cache."""
    if not CACHE_ENABLED:
        return
    _ensure_dir()
    path = _cache_path(namespace, key)
    data = {
        "namespace": namespace,
        "key": key,
        "cached_at": time.time(),
        "expires_at": time.time() + ttl_seconds,
        "value": value,
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
