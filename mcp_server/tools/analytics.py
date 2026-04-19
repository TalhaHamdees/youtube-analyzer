"""Rank videos loaded by studio_csv by a whitelisted metric."""
from __future__ import annotations

from typing import Any

import pandas as pd

from mcp_server.tools import studio_csv

ALLOWED_METRICS: tuple[str, ...] = (
    "views",
    "ctr",
    "avd_seconds",
    "impressions",
    "watch_time_hours",
)

# Fields returned per row, in order.
_OUTPUT_FIELDS: tuple[str, ...] = (
    "video_id",
    "title",
    "views",
    "ctr",
    "avd_seconds",
    "avd_text",
    "impressions",
    "watch_time_hours",
    "published_at",
)


def rank_videos(
    metric: str,
    top_n: int = 10,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Return the top_n videos sorted descending by `metric`.

    Pulls from the studio_csv cache — you must call load_studio_csv first.
    source=None uses the most recently loaded export.
    Raises ValueError on unknown metric or if no CSV has been loaded.
    """
    if metric not in ALLOWED_METRICS:
        raise ValueError(
            f"unknown metric {metric!r}; allowed: {', '.join(ALLOWED_METRICS)}"
        )
    if top_n < 1:
        raise ValueError("top_n must be >= 1")

    df = studio_csv.get_loaded(source)
    if df is None:
        raise ValueError(
            "no CSV loaded; call load_studio_csv(path) first"
            if source is None
            else f"no CSV loaded for source={source!r}"
        )

    if metric not in df.columns:
        raise ValueError(
            f"metric {metric!r} not present in loaded CSV "
            f"(columns: {', '.join(df.columns)})"
        )

    ranked = df.sort_values(by=metric, ascending=False, na_position="last").head(top_n)

    rows: list[dict[str, Any]] = []
    for _, record in ranked.iterrows():
        row: dict[str, Any] = {}
        for field in _OUTPUT_FIELDS:
            if field in ranked.columns:
                value = record[field]
                # pd.isna catches NaN, NaT, and pd.NA uniformly — bare `!= self`
                # throws on pd.NA, and `value is None` misses numpy.nan.
                if pd.isna(value):
                    row[field] = None
                else:
                    row[field] = value.item() if hasattr(value, "item") else value
        rows.append(row)
    return rows


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(rank_videos)
