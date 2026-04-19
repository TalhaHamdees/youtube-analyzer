"""Tests for mcp_server.tools.thumbnails — httpx fully mocked."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from mcp_server import paths
from mcp_server.tools import thumbnails


@pytest.fixture
def tmp_thumbnail_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = tmp_path / "thumbnails"
    monkeypatch.setattr(paths, "THUMBNAIL_CACHE", cache)
    return cache


def _jpeg_bytes(width: int, height: int) -> bytes:
    """Produce an honest JPEG payload at the given dimensions."""
    buf = BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _response(status: int, content: bytes = b"",
               content_type: str = "image/jpeg") -> MagicMock:
    """Minimal httpx.Response stand-in with the attrs the code uses."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.content = content
    r.headers = {"content-type": content_type}
    return r


def _make_client(responses_by_suffix: dict[str, MagicMock]) -> MagicMock:
    """Return a MagicMock Client whose .get() dispatches on URL suffix."""
    client = MagicMock()
    def _get(url: str, **_kwargs: Any) -> MagicMock:
        for suffix, resp in responses_by_suffix.items():
            if url.endswith(suffix):
                return resp
        raise AssertionError(f"unexpected URL: {url}")
    client.get.side_effect = _get
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    return client


def test_rejects_invalid_video_id(tmp_thumbnail_cache: Path):
    assert thumbnails.get_thumbnail("short")["error"] == "invalid_video_id"


def test_rejects_unknown_size(tmp_thumbnail_cache: Path):
    assert thumbnails.get_thumbnail(
        "aaaaaaaaaaa", size="huge"
    )["error"] == "invalid_size"


def test_happy_path_saves_and_probes_dimensions(tmp_thumbnail_cache: Path):
    client = _make_client({
        "maxresdefault.jpg": _response(200, _jpeg_bytes(1280, 720)),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("dQw4w9WgXcQ", "maxresdefault")
    assert "error" not in result
    assert result["used_size"] == "maxresdefault"
    assert result["width"] == 1280
    assert result["height"] == 720
    assert Path(result["path"]).exists()
    assert result["cached"] is False


def test_falls_back_when_maxres_404s(tmp_thumbnail_cache: Path):
    """Older videos don't have maxresdefault — must fall through to sd/hq."""
    client = _make_client({
        "maxresdefault.jpg": _response(404),
        "sddefault.jpg": _response(404),
        "hqdefault.jpg": _response(200, _jpeg_bytes(480, 360)),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("aaaaaaaaaaa", "maxresdefault")
    assert result["used_size"] == "hqdefault"
    assert result["width"] == 480


def test_all_sizes_unavailable_returns_structured_error(tmp_thumbnail_cache: Path):
    client = _make_client({
        "maxresdefault.jpg": _response(404),
        "sddefault.jpg": _response(404),
        "hqdefault.jpg": _response(404),
        "mqdefault.jpg": _response(404),
        "default.jpg": _response(404),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("aaaaaaaaaaa", "maxresdefault")
    assert result["error"] == "thumbnail_unavailable"


def test_cache_hit_returns_without_network(tmp_thumbnail_cache: Path):
    client = _make_client({
        "maxresdefault.jpg": _response(200, _jpeg_bytes(1280, 720)),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        first = thumbnails.get_thumbnail("bbbbbbbbbbb", "maxresdefault")

    # Second call must NOT create a client at all.
    with patch(
        "mcp_server.tools.thumbnails.httpx.Client",
        side_effect=AssertionError("cache hit should skip network"),
    ):
        second = thumbnails.get_thumbnail("bbbbbbbbbbb", "maxresdefault")
    assert second["cached"] is True
    assert second["path"] == first["path"]


def test_network_error_on_first_size_tries_next(tmp_thumbnail_cache: Path):
    """A transient httpx.RequestError on one size must not abort the chain."""
    def _get(url: str, **_kwargs: Any) -> MagicMock:
        if url.endswith("maxresdefault.jpg"):
            raise httpx.ConnectError("transient")
        if url.endswith("sddefault.jpg"):
            return _response(200, _jpeg_bytes(640, 480))
        return _response(404)

    client = MagicMock()
    client.get.side_effect = _get
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("ccccccccccc", "maxresdefault")
    assert result["used_size"] == "sddefault"


def test_non_image_response_does_not_poison_cache(tmp_thumbnail_cache: Path):
    """A 200 response with an HTML body must not get cached as a JPEG."""
    client = _make_client({
        "maxresdefault.jpg": _response(
            200, b"<html>captcha</html>", content_type="text/html",
        ),
        "sddefault.jpg": _response(200, _jpeg_bytes(640, 480)),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("eeeeeeeeeee", "maxresdefault")
    assert result["used_size"] == "sddefault"
    # The HTML response must not have landed on disk.
    maxres_file = tmp_thumbnail_cache / "eeeeeeeeeee_maxresdefault.jpg"
    assert not maxres_file.exists()


def test_truncated_image_rejected(tmp_thumbnail_cache: Path):
    """A 200 response with bytes that don't decode must fall through."""
    client = _make_client({
        "maxresdefault.jpg": _response(200, b"\xff\xd8garbage-not-a-jpeg"),
        "sddefault.jpg": _response(200, _jpeg_bytes(640, 480)),
    })
    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("fffffffffff", "maxresdefault")
    assert result["used_size"] == "sddefault"


def test_requested_default_skips_higher_sizes(tmp_thumbnail_cache: Path):
    """Requesting 'default' (the smallest) should not even try larger sizes."""
    visited: list[str] = []

    def _get(url: str, **_kwargs: Any) -> MagicMock:
        visited.append(url)
        return _response(200, _jpeg_bytes(120, 90))

    client = MagicMock()
    client.get.side_effect = _get
    client.__enter__.return_value = client
    client.__exit__.return_value = None

    with patch("mcp_server.tools.thumbnails.httpx.Client", return_value=client):
        result = thumbnails.get_thumbnail("ddddddddddd", "default")
    assert result["used_size"] == "default"
    assert len(visited) == 1
    assert visited[0].endswith("default.jpg")
