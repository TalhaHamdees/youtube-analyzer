"""Tests for mcp_server.tools.studio_csv."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mcp_server.tools import studio_csv


def test_loads_utf16_tab_delimited(studio_utf16_tab: Path):
    result = studio_csv.load_studio_csv(str(studio_utf16_tab))
    assert "error" not in result
    assert result["encoding"] == "utf-16"
    assert result["delimiter"] == "\\t"
    # 5 real rows after the Total aggregate is dropped.
    assert result["rows"] == 5


def test_loads_utf8_comma_delimited(studio_utf8_comma: Path):
    result = studio_csv.load_studio_csv(str(studio_utf8_comma))
    assert "error" not in result
    assert result["encoding"] == "utf-8"
    assert result["delimiter"] == ","
    assert result["rows"] == 5


def test_drops_total_aggregate_row(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df = studio_csv.get_loaded()
    assert df is not None
    # "Total" should not appear in video_id column.
    assert "Total" not in df["video_id"].tolist()
    assert "total" not in (s.lower() for s in df["video_id"].tolist())


def test_fuzzy_column_match_produces_canonical_names(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df = studio_csv.get_loaded()
    assert df is not None
    expected = {"video_id", "title", "views", "watch_time_hours",
                "avd_text", "impressions", "ctr", "published_at"}
    assert expected.issubset(set(df.columns))


def test_avd_hhmmss_converted_to_seconds(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df = studio_csv.get_loaded()
    assert df is not None
    # Row with AVD "0:04:12" -> 252 seconds.
    row = df[df["video_id"] == "aaaaaaaaaaa"].iloc[0]
    assert row["avd_seconds"] == pytest.approx(252.0)


def test_avd_mmss_normalized(studio_utf16_tab: Path):
    """AVD with no hour field ('1:12') must still parse to 72 seconds."""
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df = studio_csv.get_loaded()
    assert df is not None
    row = df[df["video_id"] == "ddddddddddd"].iloc[0]
    assert row["avd_seconds"] == pytest.approx(72.0)


def test_numeric_columns_are_numeric(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df = studio_csv.get_loaded()
    assert df is not None
    for col in ("views", "ctr", "impressions", "watch_time_hours"):
        assert pd.api.types.is_numeric_dtype(df[col]), f"{col} is not numeric"


def test_cache_returns_same_object_without_reload(studio_utf16_tab: Path):
    """get_loaded() returns the cached frame identity (no re-parse)."""
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df_a = studio_csv.get_loaded()
    df_b = studio_csv.get_loaded()
    assert df_a is df_b  # same object — no re-read from disk


def test_reload_replaces_frame_for_same_source(studio_utf16_tab: Path):
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df_a = studio_csv.get_loaded()
    studio_csv.load_studio_csv(str(studio_utf16_tab))
    df_b = studio_csv.get_loaded()
    assert df_b is not df_a and df_b.equals(df_a)


def test_missing_file_returns_structured_error(tmp_path: Path):
    result = studio_csv.load_studio_csv(str(tmp_path / "nope.csv"))
    assert result.get("error") == "file_not_found"


def test_get_loaded_returns_none_when_nothing_loaded():
    assert studio_csv.get_loaded() is None


def test_preview_is_json_serializable(tmp_path: Path):
    """A row with a missing AVD produces NaN in avd_seconds; preview must not carry NaN floats."""
    import json
    rows = [
        ("Video", "Video title", "Views", "Average view duration"),
        ("Total", "", "100", "0:01:00"),
        ("aaaaaaaaaaa", "Normal video", "10", "0:02:00"),
        ("bbbbbbbbbbb", "Broken AVD", "5", "not-a-duration"),
    ]
    body = "\n".join("\t".join(r) for r in rows) + "\n"
    path = tmp_path / "missing.csv"
    path.write_text(body, encoding="utf-16")
    result = studio_csv.load_studio_csv(str(path))
    assert "error" not in result
    # If preview leaks NaN, this raises ValueError: "Out of range float values".
    json.dumps(result["preview"])


def test_total_only_export_yields_empty_frame(tmp_path: Path):
    """An export where only the Total aggregate row exists should produce 0 rows — no crash."""
    rows = [
        ("Video", "Video title", "Views"),
        ("Total", "", "0"),
    ]
    body = "\n".join("\t".join(r) for r in rows) + "\n"
    path = tmp_path / "empty.csv"
    path.write_text(body, encoding="utf-16")
    result = studio_csv.load_studio_csv(str(path))
    assert result.get("rows") == 0
    assert result.get("preview") == []
