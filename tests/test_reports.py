"""Tests for mcp_server.tools.reports.save_report."""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server import paths
from mcp_server.tools import reports


@pytest.fixture
def tmp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "REPORTS_DIR", tmp_path / "reports")
    return tmp_path / "reports"


def test_writes_markdown_to_reports_dir(tmp_reports: Path):
    result = reports.save_report("mkbhd-SOP", "# Title\n\nBody.")
    assert "error" not in result
    assert result["filename"] == "mkbhd-SOP.md"
    path = Path(result["path"])
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# Title\n\nBody."
    assert result["bytes"] == len(b"# Title\n\nBody.")


def test_name_is_slugged(tmp_reports: Path):
    result = reports.save_report("some / weird / name!!", "content")
    assert result["filename"] == "some-weird-name.md"


def test_empty_markdown_rejected(tmp_reports: Path):
    assert reports.save_report("x", "")["error"] == "empty_report"
    assert reports.save_report("x", "   \n  ")["error"] == "empty_report"


def test_existing_md_extension_preserved(tmp_reports: Path):
    result = reports.save_report("already.md", "# hi")
    assert result["filename"] == "already.md"


def test_utf8_round_trip(tmp_reports: Path):
    body = "# Café — résumé — 数据 — émoji 🎬"
    result = reports.save_report("utf8-test", body)
    assert Path(result["path"]).read_text(encoding="utf-8") == body


def test_all_punctuation_name_falls_back(tmp_reports: Path):
    """A name of only punctuation slugs to empty — must default to 'report.md'."""
    result = reports.save_report("!!!///", "body")
    assert result["filename"] == "report.md"
