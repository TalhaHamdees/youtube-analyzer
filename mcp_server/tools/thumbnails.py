"""Download YouTube thumbnails to disk so Claude can read them via vision.

YouTube hosts thumbnails at deterministic URLs keyed by video_id + size suffix.
``maxresdefault`` (1280x720) is not produced for every video — older or less
popular uploads 404 at max res, so we fall back through smaller sizes in order
until one resolves. Downloaded files are cached forever (thumbnails are
immutable for a given video_id).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from mcp_server import paths

_log = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_TEMPLATE = "https://img.youtube.com/vi/{video_id}/{suffix}"

# Size -> URL filename suffix, expected dimensions (w, h).
_SIZES: dict[str, tuple[str, tuple[int, int]]] = {
    "default": ("default.jpg", (120, 90)),
    "mqdefault": ("mqdefault.jpg", (320, 180)),
    "hqdefault": ("hqdefault.jpg", (480, 360)),
    "sddefault": ("sddefault.jpg", (640, 480)),
    "maxresdefault": ("maxresdefault.jpg", (1280, 720)),
}
_ALLOWED_SIZES = tuple(_SIZES.keys())

# Fallback order when a larger size 404s. ``default`` (120x90) always exists.
_FALLBACK_ORDER: tuple[str, ...] = (
    "maxresdefault",
    "sddefault",
    "hqdefault",
    "mqdefault",
    "default",
)


def _cache_path(video_id: str, size: str) -> Path:
    return paths.THUMBNAIL_CACHE / f"{video_id}_{size}.jpg"


def _probe_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as im:
            return im.size[0], im.size[1]
    except (UnidentifiedImageError, OSError):
        return (None, None)


def _download(video_id: str, size: str, client: httpx.Client) -> Path | None:
    """Download one size; return local path on a valid image, None otherwise.

    Validates that the response is an actual image (content-type header +
    Pillow decode check) before caching. A 200 response with a captcha / HTML
    body would otherwise poison the cache forever, since the cache has no TTL.
    """
    suffix, _ = _SIZES[size]
    url = _URL_TEMPLATE.format(video_id=video_id, suffix=suffix)
    try:
        response = client.get(url, follow_redirects=True, timeout=15.0)
    except httpx.RequestError:
        return None
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        _log.warning("thumbnail fetch status=%s size=%s video=%s",
                     response.status_code, size, video_id)
        return None

    content_type = (response.headers.get("content-type") or "").lower()
    if content_type and not content_type.startswith("image/"):
        _log.warning("thumbnail non-image content-type=%s size=%s video=%s",
                     content_type, size, video_id)
        return None

    target = _cache_path(video_id, size)
    paths.ensure(target.parent)
    tmp = target.with_suffix(f".jpg.tmp{os.getpid()}")
    tmp.write_bytes(response.content)

    # Decode-verify before committing. Corrupt/non-image payloads get dropped
    # rather than persisted as a poison cache entry.
    if _probe_dimensions(tmp) == (None, None):
        try:
            tmp.unlink()
        except OSError:
            pass
        return None

    os.replace(tmp, target)
    return target


def get_thumbnail(video_id: str, size: str = "maxresdefault") -> dict[str, Any]:
    """Return a local path to the requested thumbnail.

    Falls through to smaller sizes if the requested one is not produced for
    this video. The returned ``used_size`` tells the caller what actually came
    back. Always returns a playable ``default`` (120x90) as a last resort — if
    even that fails, returns a structured error.
    """
    if not _VIDEO_ID_RE.match(video_id):
        return {"error": "invalid_video_id", "video_id": video_id}
    if size not in _SIZES:
        return {
            "error": "invalid_size",
            "detail": f"allowed: {list(_ALLOWED_SIZES)}",
        }

    # Build fallback chain starting from the requested size.
    try:
        start_idx = _FALLBACK_ORDER.index(size)
    except ValueError:
        start_idx = 0
    chain = _FALLBACK_ORDER[start_idx:]

    # Cache hit on any size along the chain.
    for candidate in chain:
        cached = _cache_path(video_id, candidate)
        if cached.exists():
            w, h = _probe_dimensions(cached)
            return {
                "video_id": video_id,
                "requested_size": size,
                "used_size": candidate,
                "path": str(cached),
                "width": w,
                "height": h,
                "cached": True,
            }

    # No cache hit — walk the chain until one download succeeds.
    with httpx.Client() as client:
        for candidate in chain:
            downloaded = _download(video_id, candidate, client)
            if downloaded is not None:
                w, h = _probe_dimensions(downloaded)
                return {
                    "video_id": video_id,
                    "requested_size": size,
                    "used_size": candidate,
                    "path": str(downloaded),
                    "width": w,
                    "height": h,
                    "cached": False,
                }

    return {
        "error": "thumbnail_unavailable",
        "video_id": video_id,
        "detail": f"no thumbnail served at sizes {list(chain)}",
    }


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(get_thumbnail)
