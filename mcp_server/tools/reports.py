"""Write skill-generated reports to ``data/reports/``.

Skills call ``save_report(name, markdown)`` to persist their output. The name
is slugged to produce a filesystem-safe filename — slashes, spaces, and punct.
collapse to hyphens — so skills can pass a descriptive title like
``"mkbhd-SOP"`` without worrying about portability.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from mcp_server import paths

_log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str) -> str:
    """Produce a filesystem-safe basename. Preserves case, hyphens, dots, underscores."""
    cleaned = _SLUG_RE.sub("-", name.strip()).strip("-.")
    if not cleaned:
        cleaned = "report"
    if not cleaned.endswith(".md"):
        cleaned = f"{cleaned}.md"
    return cleaned


def save_report(name: str, markdown: str) -> dict[str, Any]:
    """Write a markdown report under ``data/reports/{name}.md`` and return the absolute path."""
    if not isinstance(markdown, str) or not markdown.strip():
        return {"error": "empty_report", "detail": "markdown must be a non-empty string"}

    filename = _safe_name(name)
    target = paths.REPORTS_DIR / filename
    paths.ensure(paths.REPORTS_DIR)

    try:
        tmp = target.with_suffix(target.suffix + f".tmp{os.getpid()}")
        tmp.write_text(markdown, encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        _log.warning("report save failed for %s: %s", filename, exc)
        return {"error": "write_failed", "detail": str(exc)}

    return {
        "path": str(target),
        "filename": filename,
        "bytes": len(markdown.encode("utf-8")),
    }


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(save_report)
