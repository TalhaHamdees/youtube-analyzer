"""YouTube Data API v3 wrapper (API-key path).

Covers the public-data surface needed for competitor research:

- ``get_channel_videos(channel, limit)`` — list a channel's uploads with stats.
- ``get_video_details(video_id)`` — single-video metadata + stats.
- ``search_niche(query, region, order, limit, published_after_days)`` — niche top videos.

Quota-awareness: YouTube Data API v3 defaults to 10 000 units/day. Reads
(channels/playlistItems/videos.list) cost 1 unit; ``search.list`` costs 100.
All responses cache to ``data/cache/api/`` so re-runs within the TTL burn zero
quota. A ``refresh=True`` kwarg bypasses the cache.

Quota exhaustion and invalid keys surface as structured errors
(``{"error": "...", "detail": "..."}``) rather than exceptions.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from mcp_server import paths

_log = logging.getLogger(__name__)

# Cache TTLs (seconds). Details are stable, search is volatile.
_TTL_CHANNEL = 7 * 24 * 3600
_TTL_VIDEO = 7 * 24 * 3600
_TTL_SEARCH = 24 * 3600
_TTL_HANDLE = 30 * 24 * 3600  # channel_id rarely changes

# Regex anchors
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# YouTube handles are 3–30 chars; must start and end with alphanumerics.
_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._-]{1,28}[A-Za-z0-9]$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_YT_HOST_RE = re.compile(r"^(?:https?://)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/", re.IGNORECASE)

_client: Resource | None = None
_dotenv_loaded = False


def _load_env() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    env_path = paths.PROJECT_ROOT / "config" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _dotenv_loaded = True


def _get_client() -> Resource | dict[str, Any]:
    """Build (and memoize) the YouTube Data API client.

    Returns either the ``Resource`` or a structured error dict; callers check.
    """
    global _client
    _load_env()
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return {
            "error": "missing_api_key",
            "detail": "set YOUTUBE_API_KEY in config/.env — see config/.env.example",
        }
    if _client is None:
        _client = build(
            "youtube",
            "v3",
            developerKey=api_key,
            cache_discovery=False,
        )
    return _client


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #

def _cache_file(namespace: str, key: str) -> Path:
    return paths.API_CACHE / namespace / f"{key}.json"


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", value.strip().lower()).strip("_") or "empty"


def _cache_read(namespace: str, key: str, ttl: int) -> Any | None:
    path = _cache_file(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    age = time.time() - payload.get("_cached_at_epoch", 0)
    if age > ttl:
        return None
    return payload.get("data")


def _cache_write(namespace: str, key: str, data: Any) -> None:
    target = _cache_file(namespace, key)
    paths.ensure(target.parent)
    payload = {
        "_cached_at": datetime.now(UTC).isoformat(),
        "_cached_at_epoch": time.time(),
        "data": data,
    }
    try:
        # Atomic write: tmp + os.replace avoids readers seeing half-written JSON
        # if two calls race.
        tmp = target.with_suffix(target.suffix + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        _log.warning("api cache write failed for %s/%s: %s", namespace, key, exc)


# --------------------------------------------------------------------------- #
# Error translation
# --------------------------------------------------------------------------- #

def _translate_http_error(exc: HttpError) -> dict[str, Any]:
    """Map googleapiclient HttpError to our structured error taxonomy."""
    status = exc.resp.status
    reason = ""
    try:
        content = json.loads(exc.content.decode("utf-8"))
        errors = content.get("error", {}).get("errors") or []
        if errors:
            reason = errors[0].get("reason", "")
        message = content.get("error", {}).get("message", str(exc))
    except (ValueError, AttributeError, UnicodeDecodeError):
        message = str(exc)

    if status == 403 and reason == "quotaExceeded":
        return {"error": "quota_exceeded", "detail": message}
    if status == 429 or reason in ("rateLimitExceeded", "userRateLimitExceeded"):
        return {"error": "rate_limited", "detail": message}
    if status == 403 and reason == "keyInvalid":
        return {"error": "invalid_api_key", "detail": message}
    if status == 403 and reason == "forbidden":
        return {"error": "forbidden", "detail": message}
    if status == 400:
        return {"error": "bad_request", "detail": message}
    if status == 404:
        return {"error": "not_found", "detail": message}
    return {"error": "api_error", "status": status, "detail": message}


def _execute(request: Any) -> Any | dict[str, Any]:
    """Execute a googleapiclient request, translating errors to structured dicts."""
    try:
        return request.execute()
    except HttpError as exc:
        return _translate_http_error(exc)


# --------------------------------------------------------------------------- #
# Channel resolution
# --------------------------------------------------------------------------- #

def _extract_handle_or_id(value: str) -> tuple[str, str]:
    """Classify input as (kind, cleaned) where kind is 'id' | 'handle' | 'raw' | 'invalid'.

    Accepts raw channel IDs (``UC...``), handles (``@mkbhd`` / ``mkbhd``),
    YouTube URLs with or without scheme (``youtube.com/@mkbhd``,
    ``https://m.youtube.com/@mkbhd``), and legacy ``/c/name`` / ``/user/name``
    paths (treated as raw — requires search fallback). Explicitly rejects
    ``youtu.be/<video_id>`` shortlinks since those are videos, not channels.
    """
    v = value.strip()
    if not v:
        return ("invalid", "")

    match = _YT_HOST_RE.match(v)
    if match:
        host_and_path = v[match.start():]
        if "youtu.be/" in host_and_path.lower():
            return ("invalid", v)  # video shortlink, not a channel
        tail = v[match.end():]  # everything after "...youtube.com/"
        first_segment = tail.split("/", 1)[0].split("?", 1)[0]
        if first_segment.startswith("@"):
            v = first_segment
        elif tail.startswith("channel/"):
            v = tail.split("/", 2)[1].split("?", 1)[0]
        elif tail.startswith(("c/", "user/")):
            v = tail.split("/", 2)[1].split("?", 1)[0]
        else:
            v = first_segment  # unknown shape — let the matcher classify it

    if _CHANNEL_ID_RE.match(v):
        return ("id", v)
    if v.startswith("@"):
        v = v[1:]
        return ("handle", v) if _HANDLE_RE.match(v) else ("invalid", v)
    if _HANDLE_RE.match(v):
        return ("handle", v)
    # Fall through: treat as a name that needs a search fallback.
    return ("raw", v)


def _handle_cache_key(kind: str, cleaned: str) -> str:
    """Collision-safe cache key: literal kind + cleaned value, hashed if long.

    Using ``_slug`` collapsed separators and caused ``foo.bar`` / ``foo-bar`` /
    ``foo_bar`` to share the same cache entry — fixed here.
    """
    raw = f"{kind}__{cleaned.lower()}"
    if len(raw) > 80:
        raw = f"{kind}__{hashlib.sha256(cleaned.encode('utf-8')).hexdigest()[:32]}"
    # Replace filesystem-hostile chars only (don't collapse the separators).
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def resolve_channel_id(channel: str) -> dict[str, Any]:
    """Resolve a handle / URL / raw name to a channel_id. Returns a structured dict.

    The handle → channel_id mapping is effectively permanent, so this is always
    cache-first with a 30-day TTL. The public tools below expose ``refresh``
    for re-fetching *video data*, not for re-resolving the handle.
    """
    kind, cleaned = _extract_handle_or_id(channel)
    if kind == "id":
        return {"channel_id": cleaned, "resolved_via": "direct"}
    if kind == "invalid":
        return {
            "error": "invalid_channel",
            "detail": f"could not parse {channel!r} as a channel handle, URL, or ID",
        }

    cache_key = _handle_cache_key(kind, cleaned)
    cached = _cache_read("handles", cache_key, _TTL_HANDLE)
    if cached:
        return cached

    client = _get_client()
    if isinstance(client, dict):
        return client

    if kind == "handle":
        resp = _execute(client.channels().list(part="id,snippet", forHandle=cleaned))
        if isinstance(resp, dict) and "error" in resp:
            return resp
        items = resp.get("items") or []
        if items:
            result = {
                "channel_id": items[0]["id"],
                "title": items[0]["snippet"]["title"],
                "resolved_via": "forHandle",
            }
            _cache_write("handles", cache_key, result)
            return result

    # Fallback: search for the name and take the top channel result. Flag low
    # confidence when the returned title doesn't clearly match the input, so
    # callers can decide whether to trust it.
    resp = _execute(client.search().list(
        part="snippet", q=cleaned, type="channel", maxResults=1,
    ))
    if isinstance(resp, dict) and "error" in resp:
        return resp
    items = resp.get("items") or []
    if not items:
        return {"error": "channel_not_found", "detail": f"no channel for {channel!r}"}
    title = items[0]["snippet"]["channelTitle"]
    confident = cleaned.lower() in title.lower() or title.lower() in cleaned.lower()
    result = {
        "channel_id": items[0]["snippet"]["channelId"],
        "title": title,
        "resolved_via": "search" if confident else "search_low_confidence",
    }
    _cache_write("handles", cache_key, result)
    return result


# --------------------------------------------------------------------------- #
# Video hydration
# --------------------------------------------------------------------------- #

def _hydrate_videos(
    client: Resource, video_ids: list[str], refresh: bool = False
) -> list[dict[str, Any]] | dict[str, Any]:
    """Fetch full video records for up to 50 ids/batch. Populates the videos cache."""
    hydrated: list[dict[str, Any]] = []
    missing: list[str] = []
    for vid in video_ids:
        if refresh:
            missing.append(vid)
            continue
        cached = _cache_read("videos", vid, _TTL_VIDEO)
        if cached is not None:
            hydrated.append(cached)
        else:
            missing.append(vid)

    # Batch up to 50 ids per videos.list call.
    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        resp = _execute(client.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
            maxResults=50,
        ))
        if isinstance(resp, dict) and "error" in resp:
            return resp
        for item in resp.get("items", []):
            record = _slim_video(item)
            _cache_write("videos", record["video_id"], record)
            hydrated.append(record)

    # Preserve input order.
    by_id = {r["video_id"]: r for r in hydrated}
    return [by_id[v] for v in video_ids if v in by_id]


def _slim_video(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})
    return {
        "video_id": item["id"],
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "tags": snippet.get("tags", []),
        "duration": details.get("duration"),
        "thumbnail_url": (snippet.get("thumbnails", {})
                          .get("maxres", {})
                          .get("url")
                          or snippet.get("thumbnails", {})
                          .get("high", {})
                          .get("url")),
        "views": int(stats["viewCount"]) if "viewCount" in stats else None,
        "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
        "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
    }


# --------------------------------------------------------------------------- #
# Public tools
# --------------------------------------------------------------------------- #

def get_channel_videos(
    channel: str, limit: int = 20, refresh: bool = False
) -> dict[str, Any]:
    """Return the most recent ``limit`` uploads from a channel, hydrated with stats.

    ``refresh=True`` re-fetches video data from the API but keeps the handle
    cache sticky (handle → channel_id essentially never changes).
    """
    if limit < 1:
        return {"error": "invalid_limit", "detail": "limit must be >= 1"}

    resolved = resolve_channel_id(channel)
    if "error" in resolved:
        return resolved
    channel_id = resolved["channel_id"]

    cache_key = f"{channel_id}__limit_{limit}"
    cached = _cache_read("channel_videos", cache_key, _TTL_CHANNEL) if not refresh else None
    if cached is not None:
        return cached

    client = _get_client()
    if isinstance(client, dict):
        return client

    ch_resp = _execute(client.channels().list(part="contentDetails", id=channel_id))
    if isinstance(ch_resp, dict) and "error" in ch_resp:
        return ch_resp
    items = ch_resp.get("items") or []
    if not items:
        return {"error": "channel_not_found", "channel_id": channel_id}
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while len(video_ids) < limit:
        page_size = min(50, limit - len(video_ids))
        resp = _execute(client.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=page_size,
            pageToken=page_token,
        ))
        if isinstance(resp, dict) and "error" in resp:
            return resp
        for item in resp.get("items", []):
            vid = item["contentDetails"]["videoId"]
            if vid not in seen:
                seen.add(vid)
                video_ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = _hydrate_videos(client, video_ids[:limit], refresh=refresh)
    if isinstance(videos, dict):
        return videos

    result = {
        "channel_id": channel_id,
        "channel_title": resolved.get("title"),
        "count": len(videos),
        "videos": videos,
    }
    _cache_write("channel_videos", cache_key, result)
    return result


def get_video_details(video_id: str, refresh: bool = False) -> dict[str, Any]:
    """Return snippet + statistics + contentDetails for a single video."""
    if not _VIDEO_ID_RE.match(video_id):
        return {"error": "invalid_video_id", "video_id": video_id}

    if not refresh:
        cached = _cache_read("videos", video_id, _TTL_VIDEO)
        if cached is not None:
            return cached

    client = _get_client()
    if isinstance(client, dict):
        return client

    resp = _execute(client.videos().list(
        part="snippet,statistics,contentDetails",
        id=video_id,
    ))
    if isinstance(resp, dict) and "error" in resp:
        return resp
    items = resp.get("items") or []
    if not items:
        return {"error": "video_not_found", "video_id": video_id}

    record = _slim_video(items[0])
    _cache_write("videos", video_id, record)
    return record


def search_niche(
    query: str,
    region: str = "US",
    order: str = "viewCount",
    limit: int = 25,
    published_after_days: int = 90,
    refresh: bool = False,
) -> dict[str, Any]:
    """Search for top videos in a niche. Hydrates the first page with full stats.

    Quota: search.list = 100 units per call, so this is the most expensive tool.
    Default TTL of 24h amortizes the cost across re-runs.
    """
    if limit < 1:
        return {"error": "invalid_limit", "detail": "limit must be >= 1"}
    allowed_order = {"viewCount", "date", "relevance", "rating", "title"}
    if order not in allowed_order:
        return {
            "error": "invalid_order",
            "detail": f"allowed: {sorted(allowed_order)}",
        }

    published_after = (
        datetime.now(UTC) - timedelta(days=published_after_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    cache_key = "__".join([
        _slug(query),
        region.lower(),
        order,
        f"limit_{limit}",
        f"after_{published_after_days}d",
    ])
    cached = _cache_read("search", cache_key, _TTL_SEARCH) if not refresh else None
    if cached is not None:
        return cached

    client = _get_client()
    if isinstance(client, dict):
        return client

    video_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while len(video_ids) < limit:
        page_size = min(50, limit - len(video_ids))
        resp = _execute(client.search().list(
            part="snippet",
            q=query,
            type="video",
            order=order,
            regionCode=region,
            publishedAfter=published_after,
            maxResults=page_size,
            pageToken=page_token,
        ))
        if isinstance(resp, dict) and "error" in resp:
            return resp
        for item in resp.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in seen:
                seen.add(vid)
                video_ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = _hydrate_videos(client, video_ids[:limit], refresh=refresh)
    if isinstance(videos, dict):
        return videos

    result = {
        "query": query,
        "region": region,
        "order": order,
        "published_after": published_after,
        "count": len(videos),
        "videos": videos,
    }
    _cache_write("search", cache_key, result)
    return result


# --------------------------------------------------------------------------- #
# Test hooks — module-level resets
# --------------------------------------------------------------------------- #

def _reset_for_tests() -> None:
    global _client, _dotenv_loaded
    _client = None
    _dotenv_loaded = False


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(get_channel_videos)
    mcp.tool()(get_video_details)
    mcp.tool()(search_niche)
