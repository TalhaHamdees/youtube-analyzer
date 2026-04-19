"""Shared pytest fixtures — generate Studio-format sample CSVs in tmp_path."""
from __future__ import annotations

from pathlib import Path

import pytest

# Representative Studio-style rows. First data row is "Total" (dropped).
# Columns mirror a real export: `Video` = video ID, CTR has %, AVD is hh:mm:ss.
_ROWS: list[tuple[str, ...]] = [
    ("Video", "Video title", "Views", "Watch time (hours)",
     "Average view duration", "Impressions",
     "Impressions click-through rate (%)", "Video publish time"),
    ("Total", "", "12345", "678.9", "0:03:21", "54321", "7.12", ""),
    ("aaaaaaaaaaa", "How to build an MCP server", "5200", "210.5",
     "0:04:12", "18000", "9.80", "2026-03-01T12:00:00Z"),
    ("bbbbbbbbbbb", "YouTube analytics with pandas", "3100", "95.2",
     "0:02:45", "25000", "6.10", "2026-02-20T15:30:00Z"),
    ("ccccccccccc", "CSV parsing gotchas", "8400", "410.1",
     "0:05:55", "42000", "12.40", "2026-03-10T09:15:00Z"),
    # mm:ss edge case — AVD with no hour field.
    ("ddddddddddd", "Short video: quick tip", "1500", "18.3",
     "1:12", "7000", "4.50", "2026-03-15T18:00:00Z"),
    ("eeeeeeeeeee", "Tool design review", "2700", "62.8",
     "0:03:00", "15000", "5.75", "2026-03-18T11:00:00Z"),
]


def _rows_to_delimited(delimiter: str) -> str:
    return "\n".join(delimiter.join(row) for row in _ROWS) + "\n"


@pytest.fixture
def studio_utf16_tab(tmp_path: Path) -> Path:
    """Real-format export: UTF-16 LE with BOM, tab-separated."""
    body = _rows_to_delimited("\t")
    path = tmp_path / "studio_utf16.csv"
    path.write_text(body, encoding="utf-16")  # Python writes BOM by default.
    return path


@pytest.fixture
def studio_utf8_comma(tmp_path: Path) -> Path:
    """Fallback format: UTF-8, comma-separated."""
    body = _rows_to_delimited(",")
    path = tmp_path / "studio_utf8.csv"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _reset_studio_cache():
    """Clear module-level cache between tests so ordering doesn't matter."""
    from mcp_server.tools import studio_csv
    studio_csv._LOADED.clear()
    studio_csv._LOADED_LAST = None
    yield
    studio_csv._LOADED.clear()
    studio_csv._LOADED_LAST = None
