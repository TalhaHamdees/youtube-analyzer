"""YouTube Analytics API v2 wrapper (own-channel, OAuth-only).

Exposes ``get_my_analytics`` which queries the ``youtubeAnalytics`` v2 service
for metrics on the authenticated user's channel. Requires OAuth creds from
``mcp_server.auth.oauth.get_credentials`` — the YOUTUBE_API_KEY path cannot
reach this API.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mcp_server import cache, errors
from mcp_server.auth import oauth

_log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_TTL_MY_ANALYTICS = 3600  # 1 hour — analytics data lags; don't cache too long.

DEFAULT_METRICS: tuple[str, ...] = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "impressions",
    "impressionClickThroughRate",
    "subscribersGained",
    "subscribersLost",
)


def _reset_for_tests() -> None:
    # Kept for test API compatibility; no module-level client to reset anymore.
    return None


def _cache_key(start: str, end: str, metrics: tuple[str, ...],
               dimensions: str | None, ids: str) -> str:
    # Sort metrics so semantically identical calls share a cache entry
    # regardless of caller-supplied ordering.
    joined = "|".join(
        [start, end, ",".join(sorted(metrics)), dimensions or "-", ids]
    )
    return cache.slug(joined)


def get_my_analytics(
    start_date: str,
    end_date: str,
    metrics: list[str] | None = None,
    dimensions: str | None = None,
    channel_id: str = "MINE",
    refresh: bool = False,
) -> dict[str, Any]:
    """Query YouTube Analytics v2 for the authenticated user's channel.

    Args:
        start_date: ``YYYY-MM-DD`` inclusive.
        end_date: ``YYYY-MM-DD`` inclusive.
        metrics: list of metric names; defaults to a summary set.
        dimensions: e.g. ``day`` / ``video`` / ``traffic_source_type``.
        channel_id: ``MINE`` (default, authenticated user) or a ``UC...`` id.

    Returns:
        On success: ``{"start_date", "end_date", "columns": [...], "rows": [...], "cached": bool}``.
        On failure: ``{"error": "...", "detail": "..."}``.
    """
    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        return {"error": "invalid_date", "detail": "expected YYYY-MM-DD for start/end"}
    if start_date > end_date:
        return {"error": "invalid_date_range", "detail": "start_date must be <= end_date"}

    # Normalize channel_id: case-insensitive "MINE"/"mine"/"me" → the MINE alias.
    cid = channel_id.strip()
    if cid.upper() in ("MINE", "ME"):
        ids = "channel==MINE"
    elif _CHANNEL_ID_RE.match(cid):
        ids = f"channel=={cid}"
    else:
        return {
            "error": "invalid_channel_id",
            "detail": f"expected 'MINE' or a UC... channel id, got {channel_id!r}",
        }

    metrics_t = tuple(metrics) if metrics else DEFAULT_METRICS
    key = _cache_key(start_date, end_date, metrics_t, dimensions, ids)

    cache_ns = "my_analytics"
    if not refresh:
        cached = cache.read(cache_ns, key, _TTL_MY_ANALYTICS)
        if cached is not None:
            cached["cached"] = True
            return cached

    creds = oauth.get_credentials()
    if isinstance(creds, dict):
        return creds  # already structured error

    # Rebuild the client on every call: creds may have rotated (refresh,
    # force_reauth, different scopes) and discovery is cached by
    # googleapiclient internally so the rebuild cost is trivial.
    # cache_discovery=False avoids the legacy file-cache bug in
    # googleapis/google-api-python-client#325.
    client = build(
        "youtubeAnalytics",
        "v2",
        credentials=creds,
        cache_discovery=False,
    )

    request_kwargs: dict[str, Any] = {
        "ids": ids,
        "startDate": start_date,
        "endDate": end_date,
        "metrics": ",".join(metrics_t),
    }
    if dimensions:
        request_kwargs["dimensions"] = dimensions

    try:
        resp = client.reports().query(**request_kwargs).execute()
    except HttpError as exc:
        return errors.translate_http_error(exc)

    columns = [h.get("name") for h in resp.get("columnHeaders", [])]
    rows = resp.get("rows", []) or []

    result = {
        "start_date": start_date,
        "end_date": end_date,
        "metrics": list(metrics_t),
        "dimensions": dimensions,
        "ids": ids,
        "columns": columns,
        "rows": rows,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    cache.write(cache_ns, key, result)
    result["cached"] = False
    return result


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(get_my_analytics)
