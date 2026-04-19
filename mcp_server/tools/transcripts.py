"""Fetch YouTube video transcripts via `youtube-transcript-api`.

Cache shape: one JSON file per (video_id, requested_lang) at
``data/cache/transcripts/{video_id}.{lang}.json``. Cache never expires —
transcripts for public videos don't change.

Exposes structured errors (``{"error": "...", ...}``) rather than raising, so
Claude can recover gracefully when a video has captions disabled, is
age-restricted, etc.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from youtube_transcript_api import (
    AgeRestricted,
    FetchedTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from mcp_server import paths

_log = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _cache_path(video_id: str, lang: str) -> Path:
    return paths.TRANSCRIPT_CACHE / f"{video_id}.{lang}.json"


def _serialize(fetched: FetchedTranscript, requested_lang: str) -> dict[str, Any]:
    snippets = [
        {"t": round(s.start, 3), "d": round(s.duration, 3), "text": s.text}
        for s in fetched.snippets
    ]
    return {
        "video_id": fetched.video_id,
        "requested_lang": requested_lang,
        "used_lang": fetched.language_code,
        "language_name": fetched.language,
        "is_generated": fetched.is_generated,
        "segments": snippets,
        "text": " ".join(s["text"] for s in snippets).strip(),
        "cached_at": datetime.now(UTC).isoformat(),
    }


def _fetch_with_fallback(
    api: YouTubeTranscriptApi, video_id: str, lang: str
) -> FetchedTranscript:
    """Try the requested language; if unavailable, enumerate every available
    track and retry.

    ``YouTubeTranscriptApi.fetch`` iterates ``languages`` in priority order and
    returns the first track that matches — not a "best" match in any fuzzy
    sense. Re-raises ``NoTranscriptFound`` only when the video has zero tracks.
    """
    try:
        return api.fetch(video_id, languages=(lang,))
    except NoTranscriptFound:
        available = api.list(video_id)
        fallback_codes: list[str] = [t.language_code for t in available]
        if not fallback_codes:
            raise
        return api.fetch(video_id, languages=tuple(fallback_codes))


def get_transcript(video_id: str, lang: str = "en") -> dict[str, Any]:
    """Return a transcript dict for a YouTube video, or a structured error.

    Args:
        video_id: 11-character YouTube video ID (not a full URL).
        lang: preferred ISO 639-1 language code; falls back to any available track.

    Returns:
        On success: dict with video_id, used_lang, is_generated, segments
        (each with ``t``, ``d``, ``text``), joined ``text``, and ``cached`` flag.
        On failure: ``{"error": "<code>", "video_id": ..., "detail"?: "..."}``.
    """
    if not _VIDEO_ID_RE.match(video_id):
        return {
            "error": "invalid_video_id",
            "video_id": video_id,
            "detail": "format: expected 11 chars matching [A-Za-z0-9_-]",
        }

    cache_file = _cache_path(video_id, lang)
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["cached"] = True
            return data
        except (OSError, json.JSONDecodeError):
            # Corrupt cache — re-fetch below.
            pass

    api = YouTubeTranscriptApi()
    try:
        fetched = _fetch_with_fallback(api, video_id, lang)
    except TranscriptsDisabled:
        return {"error": "transcripts_disabled", "video_id": video_id}
    except NoTranscriptFound:
        return {"error": "no_transcript", "video_id": video_id, "requested_lang": lang}
    except VideoUnavailable:
        return {"error": "video_unavailable", "video_id": video_id}
    except VideoUnplayable as exc:
        return {"error": "video_unplayable", "video_id": video_id, "detail": str(exc)}
    except AgeRestricted:
        return {"error": "age_restricted", "video_id": video_id}
    except InvalidVideoId as exc:
        return {
            "error": "invalid_video_id",
            "video_id": video_id,
            "detail": f"upstream: {exc}",
        }
    except (IpBlocked, RequestBlocked) as exc:
        return {"error": "request_blocked", "video_id": video_id, "detail": str(exc)}
    except YouTubeTranscriptApiException as exc:
        return {"error": "fetch_failed", "video_id": video_id, "detail": str(exc)}

    result = _serialize(fetched, requested_lang=lang)
    result["cached"] = False

    paths.ensure(paths.TRANSCRIPT_CACHE)
    payload = json.dumps(result, ensure_ascii=False)
    try:
        cache_file.write_text(payload, encoding="utf-8")
        # Mirror under the used_lang so a follow-up call with the fallback
        # language hits cache instead of re-fetching.
        if result["used_lang"] != lang:
            alias = _cache_path(video_id, result["used_lang"])
            alias.write_text(payload, encoding="utf-8")
    except OSError as exc:
        _log.warning("transcript cache write failed for %s: %s", video_id, exc)

    return result


def register(mcp: Any) -> None:
    """Attach this module's MCP tools to the given FastMCP instance."""
    mcp.tool()(get_transcript)
