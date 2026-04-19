"""Tests for mcp_server.tools.transcripts. All network interaction is mocked."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from youtube_transcript_api import (
    AgeRestricted,
    FetchedTranscript,
    FetchedTranscriptSnippet,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApiException,
)

from mcp_server import paths
from mcp_server.tools import transcripts


@pytest.fixture
def tmp_transcript_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the transcript cache to a per-test tmp dir."""
    cache = tmp_path / "transcripts"
    monkeypatch.setattr(paths, "TRANSCRIPT_CACHE", cache)
    return cache


def _fake_fetched(video_id: str = "dQw4w9WgXcQ", lang: str = "en",
                  is_generated: bool = False) -> FetchedTranscript:
    snippets = [
        FetchedTranscriptSnippet(text="Hello world", start=0.0, duration=1.5),
        FetchedTranscriptSnippet(text="second line", start=1.5, duration=2.0),
    ]
    return FetchedTranscript(
        snippets=snippets,
        video_id=video_id,
        language="English",
        language_code=lang,
        is_generated=is_generated,
    )


def test_rejects_non_11_char_video_id():
    result = transcripts.get_transcript("short")
    assert result["error"] == "invalid_video_id"


def test_rejects_illegal_characters_in_video_id():
    result = transcripts.get_transcript("!!!!!!!!!!!")
    assert result["error"] == "invalid_video_id"


def test_fetch_success_writes_cache(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        return_value=_fake_fetched(),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ", "en")
    assert "error" not in result
    assert result["used_lang"] == "en"
    assert result["is_generated"] is False
    assert result["text"].startswith("Hello world")
    assert len(result["segments"]) == 2
    assert result["cached"] is False

    cached_file = tmp_transcript_cache / "dQw4w9WgXcQ.en.json"
    assert cached_file.exists()
    on_disk = json.loads(cached_file.read_text(encoding="utf-8"))
    assert on_disk["video_id"] == "dQw4w9WgXcQ"

    # Second call should hit cache — no further fetch.
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
    ) as m2:
        result2 = transcripts.get_transcript("dQw4w9WgXcQ", "en")
    m2.assert_not_called()
    assert result2["cached"] is True


def test_fallback_language_when_requested_unavailable(tmp_transcript_cache: Path):
    """Requested 'en' not available, but 'fr' is — fallback should pick 'fr'."""
    call_count = {"n": 0}

    def fetch_side_effect(self, video_id: str, languages: Any = ("en",),
                          preserve_formatting: bool = False):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: requested lang — raise.
            raise NoTranscriptFound(video_id, list(languages), None)
        return _fake_fetched(video_id, lang="fr")

    class _FakeTranscript:
        def __init__(self, code: str):
            self.language_code = code

    class _FakeList:
        def __init__(self):
            self._items = [_FakeTranscript("fr"), _FakeTranscript("de")]
        def __iter__(self):
            return iter(self._items)

    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=fetch_side_effect,
        autospec=True,
    ), patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.list",
        return_value=_FakeList(),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ", "en")

    assert "error" not in result
    assert result["requested_lang"] == "en"
    assert result["used_lang"] == "fr"


def test_transcripts_disabled_returns_structured_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=TranscriptsDisabled("dQw4w9WgXcQ"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result == {"error": "transcripts_disabled", "video_id": "dQw4w9WgXcQ"}


def test_no_transcript_found_returns_structured_error(tmp_transcript_cache: Path):
    class _EmptyList:
        def __iter__(self):
            return iter([])

    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=NoTranscriptFound("dQw4w9WgXcQ", ["en"], None),
    ), patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.list",
        return_value=_EmptyList(),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ", "en")
    assert result["error"] == "no_transcript"
    assert result["video_id"] == "dQw4w9WgXcQ"


def test_video_unavailable_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=VideoUnavailable("dQw4w9WgXcQ"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "video_unavailable"


def test_age_restricted_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=AgeRestricted("dQw4w9WgXcQ"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "age_restricted"


def test_request_blocked_returns_structured_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=RequestBlocked("dQw4w9WgXcQ"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "request_blocked"
    assert result["video_id"] == "dQw4w9WgXcQ"


def test_ip_blocked_returns_structured_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=IpBlocked("dQw4w9WgXcQ"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "request_blocked"


def test_video_unplayable_returns_structured_error(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=VideoUnplayable("dQw4w9WgXcQ", "live event has ended", []),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "video_unplayable"


def test_upstream_invalid_video_id_returns_structured_error(tmp_transcript_cache: Path):
    """Library-raised InvalidVideoId (distinct from our regex pre-check)."""
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=InvalidVideoId("aaaaaaaaaaa"),
    ):
        result = transcripts.get_transcript("aaaaaaaaaaa")
    assert result["error"] == "invalid_video_id"
    # Must disambiguate from our regex-level rejection.
    assert "upstream" in result.get("detail", "")


def test_generic_api_exception_falls_back_to_fetch_failed(tmp_transcript_cache: Path):
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=YouTubeTranscriptApiException("unexpected parse drift"),
    ):
        result = transcripts.get_transcript("dQw4w9WgXcQ")
    assert result["error"] == "fetch_failed"
    assert "unexpected parse drift" in result.get("detail", "")


def test_separate_cache_entry_per_requested_lang(tmp_transcript_cache: Path):
    """Two sequential calls with different `lang` args store under different files."""
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=[_fake_fetched(lang="en"), _fake_fetched(lang="es")],
    ) as m:
        en = transcripts.get_transcript("dQw4w9WgXcQ", "en")
        es = transcripts.get_transcript("dQw4w9WgXcQ", "es")
    assert m.call_count == 2
    assert en["used_lang"] == "en"
    assert es["used_lang"] == "es"
    assert (tmp_transcript_cache / "dQw4w9WgXcQ.en.json").exists()
    assert (tmp_transcript_cache / "dQw4w9WgXcQ.es.json").exists()


def test_fallback_writes_alias_file_for_used_lang(tmp_transcript_cache: Path):
    """After requesting 'en' and falling back to 'fr', a follow-up request for
    'fr' must hit cache rather than re-fetch."""
    class _FakeTranscript:
        def __init__(self, code: str):
            self.language_code = code

    class _FakeList:
        def __iter__(self):
            return iter([_FakeTranscript("fr")])

    # First call: requested 'en', raises, falls back to 'fr'.
    fetch_calls = {"n": 0}

    def fetch_side_effect(self, video_id: str, languages: Any = ("en",),
                          preserve_formatting: bool = False):
        fetch_calls["n"] += 1
        if fetch_calls["n"] == 1:
            raise NoTranscriptFound(video_id, list(languages), None)
        return _fake_fetched(video_id, lang="fr")

    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        side_effect=fetch_side_effect,
        autospec=True,
    ), patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.list",
        return_value=_FakeList(),
    ):
        transcripts.get_transcript("dQw4w9WgXcQ", "en")

    # Second call: direct 'fr' should hit the mirrored cache file.
    assert (tmp_transcript_cache / "dQw4w9WgXcQ.fr.json").exists()
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
    ) as m2:
        result = transcripts.get_transcript("dQw4w9WgXcQ", "fr")
    m2.assert_not_called()
    assert result["cached"] is True


def test_corrupt_cache_triggers_refetch(tmp_transcript_cache: Path):
    tmp_transcript_cache.mkdir(parents=True, exist_ok=True)
    (tmp_transcript_cache / "dQw4w9WgXcQ.en.json").write_text("not json{{", encoding="utf-8")
    with patch(
        "mcp_server.tools.transcripts.YouTubeTranscriptApi.fetch",
        return_value=_fake_fetched(),
    ) as m:
        result = transcripts.get_transcript("dQw4w9WgXcQ", "en")
    m.assert_called_once()
    assert "error" not in result
    assert result["cached"] is False
