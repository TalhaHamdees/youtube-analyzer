"""Tests for mcp_server.tools.analytics.rank_videos."""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.tools import analytics, studio_csv


def test_rank_by_views_returns_highest_first(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    rows = analytics.rank_videos("views", top_n=3)
    assert len(rows) == 3
    views = [r["views"] for r in rows]
    assert views == sorted(views, reverse=True)
    # ccccccccccc has the highest views (8400) in the fixture.
    assert rows[0]["video_id"] == "ccccccccccc"


def test_rank_by_ctr(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    rows = analytics.rank_videos("ctr", top_n=2)
    # ccccccccccc has CTR 12.40, aaaaaaaaaaa has 9.80 — top two.
    assert [r["video_id"] for r in rows] == ["ccccccccccc", "aaaaaaaaaaa"]


def test_rank_by_avd_seconds(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    rows = analytics.rank_videos("avd_seconds", top_n=1)
    # ccccccccccc = 0:05:55 = 355s, highest.
    assert rows[0]["video_id"] == "ccccccccccc"
    assert rows[0]["avd_seconds"] == pytest.approx(355.0)


def test_top_n_caps_output(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    assert len(analytics.rank_videos("views", top_n=2)) == 2
    assert len(analytics.rank_videos("views", top_n=10)) == 5  # only 5 rows exist


def test_invalid_metric_raises_with_allowed_list(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    with pytest.raises(ValueError) as exc:
        analytics.rank_videos("comments", top_n=5)
    message = str(exc.value)
    assert "comments" in message
    for allowed in analytics.ALLOWED_METRICS:
        assert allowed in message


def test_top_n_zero_raises():
    with pytest.raises(ValueError):
        analytics.rank_videos("views", top_n=0)


def test_ranking_without_load_raises():
    with pytest.raises(ValueError) as exc:
        analytics.rank_videos("views", top_n=5)
    assert "load_studio_csv" in str(exc.value)


def test_source_none_uses_most_recent(
    studio_utf16_tab: Path, studio_utf8_comma: Path
):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    studio_csv.load_studio_csv(str(studio_utf8_comma))
    # Same fixture data in both — ordering should be stable.
    rows = analytics.rank_videos("views", top_n=1)
    assert rows[0]["video_id"] == "ccccccccccc"


def test_rank_output_null_safe_on_missing_metric_values(tmp_path: Path):
    """Rows with missing values in non-sort metrics should return None, not NaN — JSON-safe."""
    rows_def = [
        ("Video", "Video title", "Views", "Watch time (hours)", "Average view duration",
         "Impressions", "Impressions click-through rate (%)"),
        ("Total", "", "0", "0", "0:00:00", "0", "0"),
        ("aaaaaaaaaaa", "complete row", "100", "5.5", "0:02:00", "1000", "3.2"),
        # ctr missing, avd missing — these become NaN after coercion.
        ("bbbbbbbbbbb", "gaps in metrics", "200", "7.1", "", "1500", ""),
    ]
    body = "\n".join("\t".join(r) for r in rows_def) + "\n"
    path = tmp_path / "gaps.csv"
    path.write_text(body, encoding="utf-16")
    studio_csv.load_studio_csv(str(path))
    ranked = analytics.rank_videos("views", top_n=5)

    import json
    json.dumps(ranked)  # would raise if NaN/NaT leaked through.

    # Row with gaps should carry explicit None for missing values.
    gaps_row = next(r for r in ranked if r["video_id"] == "bbbbbbbbbbb")
    assert gaps_row["ctr"] is None
    assert gaps_row["avd_seconds"] is None


def test_rank_on_total_only_export_returns_empty(tmp_path: Path):
    rows_def = [
        ("Video", "Video title", "Views"),
        ("Total", "", "0"),
    ]
    body = "\n".join("\t".join(r) for r in rows_def) + "\n"
    path = tmp_path / "empty.csv"
    path.write_text(body, encoding="utf-16")
    studio_csv.load_studio_csv(str(path))
    assert analytics.rank_videos("views", top_n=5) == []
