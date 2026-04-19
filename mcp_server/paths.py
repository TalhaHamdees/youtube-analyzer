"""Shared filesystem paths for the YouTube Analyzer project.

All tools that cache to disk read the roots from here so there is exactly one
place to change if the layout shifts.
"""
from __future__ import annotations

from pathlib import Path

# Repo root: mcp_server/paths.py -> mcp_server -> repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

TRANSCRIPT_CACHE = CACHE_DIR / "transcripts"
THUMBNAIL_CACHE = CACHE_DIR / "thumbnails"
API_CACHE = CACHE_DIR / "api"
OAUTH_CACHE = CACHE_DIR / "oauth"

CSV_EXPORTS_DIR = DATA_DIR / "csv_exports"
REPORTS_DIR = DATA_DIR / "reports"


def ensure(*dirs: Path) -> None:
    """Create each directory if it does not exist. No-op if already present."""
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
