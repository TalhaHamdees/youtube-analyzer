"""Tests for mcp_server.tools.youtube_api. All network interaction is mocked."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from mcp_server import paths
from mcp_server.tools import youtube_api


@pytest.fixture
def tmp_api_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = tmp_path / "api"
    monkeypatch.setattr(paths, "API_CACHE", cache)
    return cache


@pytest.fixture(autouse=True)
def _reset_youtube_api_state(monkeypatch: pytest.MonkeyPatch):
    youtube_api._reset_for_tests()
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-test-key")
    yield
    youtube_api._reset_for_tests()


# --------------------------------------------------------------------------- #
# Helpers to build fake googleapiclient responses
# --------------------------------------------------------------------------- #

def _make_client_mock(responses: dict[str, list[dict[str, Any]]]) -> MagicMock:
    """Build a MagicMock that walks the resource tree used by youtube_api.

    `responses` is keyed by endpoint name ('channels.list', 'playlistItems.list',
    'videos.list', 'search.list') and holds a list of response dicts to return
    in order, one per call.
    """
    client = MagicMock()
    counters: dict[str, int] = {k: 0 for k in responses}

    def _build_endpoint(endpoint_key: str):
        def list_fn(**kwargs):
            request = MagicMock()
            idx = counters[endpoint_key]
            counters[endpoint_key] = idx + 1
            payload = responses[endpoint_key][min(idx, len(responses[endpoint_key]) - 1)]
            if isinstance(payload, HttpError):
                request.execute.side_effect = payload
            else:
                request.execute.return_value = payload
            return request
        resource = MagicMock()
        resource.list = list_fn
        return resource

    client.channels.return_value = _build_endpoint("channels.list")
    client.playlistItems.return_value = _build_endpoint("playlistItems.list")
    client.videos.return_value = _build_endpoint("videos.list")
    client.search.return_value = _build_endpoint("search.list")
    return client


def _http_error(status: int, reason: str, message: str = "err") -> HttpError:
    resp = MagicMock(status=status, reason="")
    body = json.dumps({
        "error": {
            "message": message,
            "errors": [{"reason": reason}],
        }
    }).encode("utf-8")
    return HttpError(resp, body)


def _video_item(video_id: str, title: str = "v", views: int = 100) -> dict[str, Any]:
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": "",
            "channelId": "UCaaaaaaaaaaaaaaaaaaaaaaaa",
            "channelTitle": "c",
            "publishedAt": "2026-03-01T12:00:00Z",
            "tags": [],
            "thumbnails": {"high": {"url": f"https://img/{video_id}.jpg"}},
        },
        "statistics": {"viewCount": str(views)},
        "contentDetails": {"duration": "PT5M"},
    }


# --------------------------------------------------------------------------- #
# Missing API key
# --------------------------------------------------------------------------- #

def test_missing_api_key_returns_structured_error(
    tmp_api_cache: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    # Also prevent .env from loading a value.
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_api_cache.parent)
    result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "missing_api_key"


# --------------------------------------------------------------------------- #
# resolve_channel_id
# --------------------------------------------------------------------------- #

def test_resolve_direct_channel_id_skips_api(tmp_api_cache: Path):
    channel_id = "UC" + "a" * 22
    result = youtube_api.resolve_channel_id(channel_id)
    assert result == {"channel_id": channel_id, "resolved_via": "direct"}


def test_resolve_handle_uses_forHandle(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": [{"id": "UC123",
                                        "snippet": {"title": "MKBHD"}}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("@mkbhd")
    assert result["channel_id"] == "UC123"
    assert result["resolved_via"] == "forHandle"


def test_resolve_extracts_handle_from_url(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": [{"id": "UC456",
                                        "snippet": {"title": "MKBHD"}}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("https://www.youtube.com/@mkbhd")
    assert result["channel_id"] == "UC456"


def test_resolve_falls_back_to_search_when_handle_unknown(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": []}],
        "search.list": [{"items": [{"snippet": {
            "channelId": "UC789", "channelTitle": "legacy name"
        }}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("legacy name")
    assert result["channel_id"] == "UC789"
    assert result["resolved_via"] == "search"


def test_resolve_returns_not_found_when_no_results(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": []}],
        "search.list": [{"items": []}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("nonexistent-channel-xxx")
    assert result["error"] == "channel_not_found"


def test_resolve_caches_handle_lookup(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": [{"id": "UCabc",
                                        "snippet": {"title": "c"}}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client) as m_build:
        youtube_api.resolve_channel_id("@mkbhd")
        # Simulate a new process: reset client reference.
        youtube_api._reset_for_tests()
        # Second call hits cache — builder never called again.
        result = youtube_api.resolve_channel_id("@mkbhd")
    assert result["channel_id"] == "UCabc"
    assert m_build.call_count == 1
    # `channels.list` itself also called exactly once on the first resolve.
    assert client.channels.call_count == 1


def test_resolve_rejects_youtu_be_shortlink(tmp_api_cache: Path):
    result = youtube_api.resolve_channel_id("https://youtu.be/dQw4w9WgXcQ")
    assert result["error"] == "invalid_channel"


def test_resolve_accepts_no_scheme_url(tmp_api_cache: Path):
    client = _make_client_mock({
        "channels.list": [{"items": [{"id": "UCmob",
                                        "snippet": {"title": "Mobile MKBHD"}}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("m.youtube.com/@mkbhd")
    assert result["channel_id"] == "UCmob"


def test_resolve_low_confidence_search_fallback(tmp_api_cache: Path):
    """When search returns a channel whose title doesn't contain the input,
    flag it as low-confidence so callers can react."""
    client = _make_client_mock({
        "channels.list": [{"items": []}],
        "search.list": [{"items": [{"snippet": {
            "channelId": "UC999", "channelTitle": "Totally Different Name"
        }}]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.resolve_channel_id("my-cool-handle")
    assert result["channel_id"] == "UC999"
    assert result["resolved_via"] == "search_low_confidence"


def test_handle_cache_keys_do_not_collide_on_separators(tmp_api_cache: Path):
    """foo.bar, foo-bar, foo_bar must not share a cache entry."""
    responses = [
        {"items": [{"id": "UCdot", "snippet": {"title": "foo.bar"}}]},
        {"items": [{"id": "UCdash", "snippet": {"title": "foo-bar"}}]},
        {"items": [{"id": "UCunder", "snippet": {"title": "foo_bar"}}]},
    ]
    client = _make_client_mock({"channels.list": responses})
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        dot = youtube_api.resolve_channel_id("@foo.bar")
        dash = youtube_api.resolve_channel_id("@foo-bar")
        under = youtube_api.resolve_channel_id("@foo_bar")
    assert dot["channel_id"] == "UCdot"
    assert dash["channel_id"] == "UCdash"
    assert under["channel_id"] == "UCunder"


# --------------------------------------------------------------------------- #
# get_channel_videos
# --------------------------------------------------------------------------- #

def test_get_channel_videos_happy_path(tmp_api_cache: Path):
    channel_id = "UC" + "b" * 22
    uploads_playlist = "UU" + "b" * 22
    client = _make_client_mock({
        "channels.list": [
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
        ],
        "playlistItems.list": [{
            "items": [{"contentDetails": {"videoId": f"vid{n:08d}xxx"[:11]}}
                        for n in range(3)],
        }],
        "videos.list": [{
            "items": [_video_item(f"vid{n:08d}xxx"[:11], f"v{n}", 100 * (n + 1))
                        for n in range(3)],
        }],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_channel_videos(channel_id, limit=3)
    assert result["count"] == 3
    assert result["channel_id"] == channel_id
    assert [v["title"] for v in result["videos"]] == ["v0", "v1", "v2"]


def test_get_channel_videos_cache_hit_skips_api(tmp_api_cache: Path):
    channel_id = "UC" + "c" * 22
    uploads_playlist = "UU" + "c" * 22
    client = _make_client_mock({
        "channels.list": [
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
        ],
        "playlistItems.list": [{"items": [
            {"contentDetails": {"videoId": "aaaaaaaaaaa"}}]}],
        "videos.list": [{"items": [_video_item("aaaaaaaaaaa", "only", 1)]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        first = youtube_api.get_channel_videos(channel_id, limit=1)

    # Reset process state; second call must hit cache and never rebuild client.
    youtube_api._reset_for_tests()
    with patch(
        "mcp_server.tools.youtube_api.build",
        side_effect=AssertionError("cache miss rebuilt client"),
    ):
        second = youtube_api.get_channel_videos(channel_id, limit=1)
    assert first == second


def test_get_channel_videos_rejects_bad_limit(tmp_api_cache: Path):
    assert youtube_api.get_channel_videos("UC" + "a" * 22, limit=0)["error"] == "invalid_limit"


def test_get_channel_videos_paginates_uploads(tmp_api_cache: Path):
    """With limit=75, must page playlistItems.list at least twice."""
    channel_id = "UC" + "p" * 22
    uploads_playlist = "UU" + "p" * 22

    def _vid(n: int) -> str:
        # 11-char ids; distinct per n.
        return f"v{n:010d}"[:11]

    page_one = {
        "items": [{"contentDetails": {"videoId": _vid(n)}} for n in range(50)],
        "nextPageToken": "PAGE2",
    }
    page_two = {
        "items": [{"contentDetails": {"videoId": _vid(n)}} for n in range(50, 75)],
    }
    videos_response = {
        "items": [_video_item(_vid(n), f"v{n}", 10 * n) for n in range(75)],
    }
    client = _make_client_mock({
        "channels.list": [
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
        ],
        "playlistItems.list": [page_one, page_two],
        # Hydration may split into two videos.list calls (50 + 25).
        "videos.list": [videos_response, videos_response],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_channel_videos(channel_id, limit=75)
    assert result["count"] == 75
    assert client.playlistItems.call_count == 2


def test_get_channel_videos_deduplicates_upload_ids(tmp_api_cache: Path):
    """Duplicate videoIds from the playlist feed must not appear twice in output."""
    channel_id = "UC" + "q" * 22
    uploads_playlist = "UU" + "q" * 22
    client = _make_client_mock({
        "channels.list": [
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
        ],
        "playlistItems.list": [{
            "items": [
                {"contentDetails": {"videoId": "aaaaaaaaaaa"}},
                {"contentDetails": {"videoId": "aaaaaaaaaaa"}},
                {"contentDetails": {"videoId": "bbbbbbbbbbb"}},
            ],
        }],
        "videos.list": [{"items": [
            _video_item("aaaaaaaaaaa", "a", 1),
            _video_item("bbbbbbbbbbb", "b", 2),
        ]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_channel_videos(channel_id, limit=3)
    ids = [v["video_id"] for v in result["videos"]]
    assert ids == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_refresh_true_bypasses_cache_but_keeps_handle_sticky(tmp_api_cache: Path):
    """refresh=True re-fetches video data but does NOT re-hit the handle API."""
    channel_id = "UC" + "r" * 22
    uploads_playlist = "UU" + "r" * 22
    client = _make_client_mock({
        "channels.list": [
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
            {"items": [{"id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": uploads_playlist}}}]},
        ],
        "playlistItems.list": [
            {"items": [{"contentDetails": {"videoId": "aaaaaaaaaaa"}}]},
            {"items": [{"contentDetails": {"videoId": "aaaaaaaaaaa"}}]},
        ],
        "videos.list": [
            {"items": [_video_item("aaaaaaaaaaa", "first", 10)]},
            {"items": [_video_item("aaaaaaaaaaa", "second", 20)]},
        ],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        first = youtube_api.get_channel_videos(channel_id, limit=1)
        second = youtube_api.get_channel_videos(channel_id, limit=1, refresh=True)
    # Fresh fetch returned the updated title.
    assert first["videos"][0]["title"] == "first"
    assert second["videos"][0]["title"] == "second"


# --------------------------------------------------------------------------- #
# get_video_details
# --------------------------------------------------------------------------- #

def test_get_video_details_invalid_video_id(tmp_api_cache: Path):
    assert youtube_api.get_video_details("short")["error"] == "invalid_video_id"


def test_get_video_details_caches(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [{"items": [_video_item("aaaaaaaaaaa", "cached-ok", 42)]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        first = youtube_api.get_video_details("aaaaaaaaaaa")

    youtube_api._reset_for_tests()
    with patch("mcp_server.tools.youtube_api.build", side_effect=AssertionError("no rebuild")):
        second = youtube_api.get_video_details("aaaaaaaaaaa")
    assert first == second
    assert first["title"] == "cached-ok"


def test_get_video_details_not_found(tmp_api_cache: Path):
    client = _make_client_mock({"videos.list": [{"items": []}]})
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("bbbbbbbbbbb")
    assert result["error"] == "video_not_found"


# --------------------------------------------------------------------------- #
# Error translation
# --------------------------------------------------------------------------- #

def test_quota_exceeded_returns_structured_error(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [_http_error(403, "quotaExceeded", "out of quota")],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "quota_exceeded"


def test_invalid_api_key_returns_structured_error(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [_http_error(403, "keyInvalid", "bad key")],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "invalid_api_key"


def test_429_maps_to_rate_limited(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [_http_error(429, "userRateLimitExceeded", "slow down")],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "rate_limited"


def test_403_forbidden_maps_to_forbidden(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [_http_error(403, "forbidden", "blocked")],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "forbidden"


def test_malformed_http_error_content_falls_back_to_api_error(tmp_api_cache: Path):
    """Error response body that isn't JSON should still produce a structured error."""
    resp = MagicMock(status=500, reason="")
    bad = HttpError(resp, b"not-json-bytes<html>")
    client = _make_client_mock({"videos.list": [bad]})
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "api_error"
    assert result["status"] == 500


def test_generic_http_error_returns_api_error(tmp_api_cache: Path):
    client = _make_client_mock({
        "videos.list": [_http_error(500, "backendError", "upstream")],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.get_video_details("aaaaaaaaaaa")
    assert result["error"] == "api_error"
    assert result["status"] == 500


# --------------------------------------------------------------------------- #
# search_niche
# --------------------------------------------------------------------------- #

def test_search_niche_happy_path(tmp_api_cache: Path):
    client = _make_client_mock({
        "search.list": [{"items": [
            {"id": {"videoId": "ddddddddddd"}, "snippet": {}},
            {"id": {"videoId": "eeeeeeeeeee"}, "snippet": {}},
        ]}],
        "videos.list": [{"items": [
            _video_item("ddddddddddd", "d", 500),
            _video_item("eeeeeeeeeee", "e", 300),
        ]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        result = youtube_api.search_niche("productivity tips", limit=2)
    assert result["count"] == 2
    assert result["query"] == "productivity tips"


def test_search_niche_invalid_order(tmp_api_cache: Path):
    assert youtube_api.search_niche("x", order="popularity")["error"] == "invalid_order"


def test_search_niche_caches(tmp_api_cache: Path):
    client = _make_client_mock({
        "search.list": [{"items": [{"id": {"videoId": "fffffffffff"}, "snippet": {}}]}],
        "videos.list": [{"items": [_video_item("fffffffffff", "f", 1)]}],
    })
    with patch("mcp_server.tools.youtube_api.build", return_value=client):
        first = youtube_api.search_niche("test-query", limit=1)

    youtube_api._reset_for_tests()
    with patch("mcp_server.tools.youtube_api.build", side_effect=AssertionError("no rebuild")):
        second = youtube_api.search_niche("test-query", limit=1)
    assert first == second
