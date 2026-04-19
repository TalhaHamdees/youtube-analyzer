"""Shared disk-cache helpers for all tools that need to amortize API / network calls.

Cache layout: ``{root}/{namespace}/{key}.json`` where each file wraps the payload
in ``{"_cached_at", "_cached_at_epoch", "data"}`` so we can TTL on read without
depending on filesystem mtime (which can be reset by antivirus / sync tools).

Writes are atomic via ``tmp + os.replace`` so concurrent writers or a
mid-write crash never expose a half-written JSON document.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp_server import paths

_log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(value: str) -> str:
    """Lowercase + collapse non-alphanumerics to underscores. For cache keys."""
    return _SLUG_RE.sub("_", value.strip().lower()).strip("_") or "empty"


def _file(root: Path, namespace: str, key: str) -> Path:
    return root / namespace / f"{key}.json"


def read(namespace: str, key: str, ttl_seconds: int,
         root: Path | None = None) -> Any | None:
    """Return cached data if present and fresh; otherwise None."""
    target = _file(root or paths.API_CACHE, namespace, key)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    age = time.time() - payload.get("_cached_at_epoch", 0)
    if age > ttl_seconds:
        return None
    return payload.get("data")


def write(namespace: str, key: str, data: Any,
          root: Path | None = None) -> None:
    """Atomically write data to the cache. Silent on OSError (logged)."""
    target = _file(root or paths.API_CACHE, namespace, key)
    paths.ensure(target.parent)
    payload = {
        "_cached_at": datetime.now(UTC).isoformat(),
        "_cached_at_epoch": time.time(),
        "data": data,
    }
    try:
        tmp = target.with_suffix(target.suffix + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        _log.warning("cache write failed for %s/%s: %s", namespace, key, exc)
