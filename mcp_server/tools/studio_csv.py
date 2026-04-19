"""Parse YouTube Studio analytics CSV exports.

Real Studio exports are UTF-16 LE with BOM and tab-separated, despite the .csv
extension. Headers vary by UI locale (English/French/etc) and by which columns
the creator toggled visible in the Advanced mode view. The first data row is
a "Total" aggregate that we drop.

Because the export format is undocumented and locale-variable, we detect
encoding + delimiter by sniffing the file's first bytes and match column headers
fuzzily against a canonical-key synonym map. Unknown columns pass through
unchanged (snake_cased) so downstream code can still see them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Module-level state — fine for the single-process stdio FastMCP transport.
# If ever migrated to a multi-worker HTTP transport, move this into a
# FastMCP lifespan-scoped object instead.
_LOADED: dict[str, pd.DataFrame] = {}
_LOADED_LAST: str | None = None

# Canonical key -> lowercased header synonyms seen in real Studio exports.
# Matched after header normalization (lowercase, strip %/()/whitespace).
_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "video_id": ("video", "video id"),
    "title": ("video title", "title"),
    "views": ("views", "view count"),
    "impressions": ("impressions",),
    "ctr": (
        "impressions click-through rate",
        "impressions ctr",
        "click-through rate",
        "ctr",
    ),
    "avd_text": ("average view duration", "avg view duration", "avd"),
    "avp": ("average percentage viewed", "avg percentage viewed"),
    "watch_time_hours": ("watch time hours", "watch time"),
    "subscribers": ("subscribers", "subscribers gained"),
    "published_at": ("video publish time", "publish time", "published at", "publish date"),
    "likes": ("likes",),
    "comments": ("comments",),
    "shares": ("shares",),
}


@dataclass(frozen=True)
class _Sniffed:
    encoding: str
    delimiter: str


def _sniff(path: Path) -> _Sniffed:
    """Detect encoding (UTF-16 via BOM) and delimiter (tab vs comma) from the file head."""
    with path.open("rb") as f:
        head = f.read(4096)

    # BOM detection: UTF-16 LE (ff fe) / BE (fe ff) / UTF-8 (ef bb bf).
    if head.startswith(b"\xff\xfe"):
        encoding = "utf-16"
    elif head.startswith(b"\xfe\xff"):
        encoding = "utf-16-be"
    elif head.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"

    try:
        sample = head.decode(encoding, errors="replace")
    except LookupError:
        sample = head.decode("utf-8", errors="replace")

    first_line = sample.splitlines()[0] if sample else ""
    tabs = first_line.count("\t")
    commas = first_line.count(",")
    delimiter = "\t" if tabs >= commas and tabs > 0 else ","
    return _Sniffed(encoding=encoding, delimiter=delimiter)


_PAREN_RE = re.compile(r"\([^)]*\)")
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _normalize_header(header: str) -> str:
    """Lowercase, strip parenthetical units, collapse non-alphanumerics to spaces."""
    h = header.strip().lower()
    h = h.replace("%", "")
    h = _PAREN_RE.sub(" ", h)
    h = _NONWORD_RE.sub(" ", h)
    return " ".join(h.split())


def _canonical_column_map(headers: list[str]) -> dict[str, str]:
    """Map source header -> canonical name. Unknown headers get snake_cased as-is.

    Scoring: an exact match against a normalized synonym always beats a
    word-boundary containment match. This prevents a short synonym (e.g.
    ``impressions``) from hijacking a longer header (``Impressions
    click-through rate``) that should canonicalize to a different key.
    """
    normalized_synonyms = {
        canonical: tuple(_normalize_header(syn) for syn in synonyms)
        for canonical, synonyms in _COLUMN_SYNONYMS.items()
    }

    out: dict[str, str] = {}
    used_canonical: set[str] = set()
    for raw in headers:
        norm = _normalize_header(raw)
        best: tuple[int, str] | None = None  # (score, canonical)
        for canonical, synonyms in normalized_synonyms.items():
            if canonical in used_canonical:
                continue
            for syn in synonyms:
                if not syn:
                    continue
                if norm == syn:
                    score = 1000 + len(syn)
                elif re.search(rf"\b{re.escape(syn)}\b", norm):
                    score = len(syn)
                else:
                    continue
                if best is None or score > best[0]:
                    best = (score, canonical)
        if best is None:
            matched = _NONWORD_RE.sub("_", norm).strip("_") or f"col_{len(out)}"
        else:
            matched = best[1]
            used_canonical.add(matched)  # only lock real canonical matches
        out[raw] = matched
    return out


def _avd_to_seconds(series: pd.Series) -> pd.Series:
    """Convert hh:mm:ss (or mm:ss) strings to float seconds. Unparseable -> NaN."""
    s = series.astype("string").fillna("")
    # pd.to_timedelta does not accept mm:ss — prefix "0:" to one-colon rows.
    one_colon = s.str.count(":") == 1
    normalized = s.where(~one_colon, "0:" + s)
    td = pd.to_timedelta(normalized, errors="coerce")
    return td.dt.total_seconds()


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Best-effort numeric coercion: strip commas (US thousands), percent signs, whitespace.

    Note: assumes US-style numbers (comma thousands, dot decimal). Non-US Studio
    exports (e.g. French) use dot thousands and comma decimal — add locale
    detection if that use-case appears.
    """
    if pd.api.types.is_numeric_dtype(series):
        return series
    s = series.astype("string").fillna("")
    s = s.str.replace(",", "", regex=False)
    s = s.str.replace("%", "", regex=False)
    s = s.str.strip()
    return pd.to_numeric(s, errors="coerce")


def _drop_total_row(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the YouTube Studio 'Total' aggregate row if it appears first.

    Studio writes 'Total' into whichever column is first in the export order,
    which varies by which columns the creator had visible in Advanced mode.
    We check by position (`iloc[0]`) because column-name lookups are unreliable
    when the export is non-English.
    """
    if df.empty:
        return df
    first = df.iloc[0]
    candidates = [first.get("video_id"), first.get("title"), first.iloc[0]]
    for value in candidates:
        if isinstance(value, str) and value.strip().lower() == "total":
            return df.iloc[1:].reset_index(drop=True)
    return df


def load_studio_csv(path: str) -> dict[str, Any]:
    """Parse a YouTube Studio analytics CSV export.

    Handles UTF-16/UTF-8 encoding, tab/comma delimiters, the 'Total' aggregate
    row, and locale-variable column headers. Caches the parsed DataFrame by
    absolute path so rank_videos can reuse it.
    """
    p = Path(path).resolve()
    if not p.exists():
        return {"error": "file_not_found", "path": str(p)}
    if not p.is_file():
        return {"error": "not_a_file", "path": str(p)}

    try:
        sniffed = _sniff(p)
        df = pd.read_csv(
            p,
            encoding=sniffed.encoding,
            sep=sniffed.delimiter,
            dtype=str,
            keep_default_na=False,
            engine="python",
        )
    except (UnicodeError, pd.errors.ParserError, ValueError, OSError) as exc:
        return {"error": "parse_failed", "path": str(p), "detail": str(exc)}

    header_map = _canonical_column_map(list(df.columns))
    df = df.rename(columns=header_map)
    df = _drop_total_row(df)

    # Numeric coercions on known columns.
    for col in ("views", "impressions", "ctr", "watch_time_hours",
                "subscribers", "likes", "comments", "shares", "avp"):
        if col in df.columns:
            df[col] = _coerce_numeric(df[col])

    # AVD: parse hh:mm:ss to seconds, keep the original string too.
    if "avd_text" in df.columns:
        df["avd_seconds"] = _avd_to_seconds(df["avd_text"])

    key = str(p)
    _LOADED[key] = df
    global _LOADED_LAST
    _LOADED_LAST = key

    return {
        "source": key,
        "rows": len(df),
        "columns": list(df.columns),
        "encoding": sniffed.encoding,
        "delimiter": "\\t" if sniffed.delimiter == "\t" else sniffed.delimiter,
        "loaded_at": datetime.now(UTC).isoformat(),
        "preview": _records_json_safe(df.head(3)),
    }


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a frame to records where NaN/NaT become None (JSON-serializable)."""
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        rows.append({k: (None if pd.isna(v) else v) for k, v in record.items()})
    return rows


def get_loaded(source: str | None = None) -> pd.DataFrame | None:
    """Return a cached DataFrame. source=None returns the most recently loaded."""
    if source is None:
        return _LOADED.get(_LOADED_LAST) if _LOADED_LAST else None
    return _LOADED.get(str(Path(source).resolve()))


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(load_studio_csv)
