"""Tests for mcp_server.tools.my_analytics — OAuth + network mocked."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mcp_server import paths
from mcp_server.auth import oauth
from mcp_server.tools import my_analytics


@pytest.fixture
def tmp_api_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = tmp_path / "api"
    monkeypatch.setattr(paths, "API_CACHE", cache)
    return cache


@pytest.fixture(autouse=True)
def _reset_state():
    my_analytics._reset_for_tests()
    yield
    my_analytics._reset_for_tests()


def _fake_creds() -> MagicMock:
    return MagicMock(spec=oauth.Credentials, valid=True)


def _mock_client(rows: list[list[Any]] | None = None,
                  columns: list[str] | None = None) -> MagicMock:
    client = MagicMock()
    columns = columns or ["day", "views"]
    rows = rows if rows is not None else [["2026-03-01", 100], ["2026-03-02", 120]]
    client.reports.return_value.query.return_value.execute.return_value = {
        "columnHeaders": [{"name": c} for c in columns],
        "rows": rows,
    }
    return client


def test_rejects_bad_date_format(tmp_api_cache: Path):
    result = my_analytics.get_my_analytics("2026/03/01", "2026-03-02")
    assert result["error"] == "invalid_date"


def test_rejects_inverted_date_range(tmp_api_cache: Path):
    result = my_analytics.get_my_analytics("2026-03-10", "2026-03-01")
    assert result["error"] == "invalid_date_range"


def test_returns_oauth_error_when_not_configured(tmp_api_cache: Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        oauth, "get_credentials",
        lambda *_, **__: {"error": "oauth_not_configured", "detail": "x"},
    )
    result = my_analytics.get_my_analytics("2026-03-01", "2026-03-02")
    assert result["error"] == "oauth_not_configured"


def test_happy_path_returns_rows_and_caches(tmp_api_cache: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = _mock_client()
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        result = my_analytics.get_my_analytics(
            "2026-03-01", "2026-03-07", dimensions="day",
        )
    assert "error" not in result
    assert result["columns"] == ["day", "views"]
    assert result["rows"] == [["2026-03-01", 100], ["2026-03-02", 120]]
    assert result["cached"] is False

    # Second call within TTL: cache hit, no network.
    my_analytics._reset_for_tests()
    with patch(
        "mcp_server.tools.my_analytics.build",
        side_effect=AssertionError("cache miss rebuilt client"),
    ):
        again = my_analytics.get_my_analytics(
            "2026-03-01", "2026-03-07", dimensions="day",
        )
    assert again["cached"] is True
    assert again["rows"] == result["rows"]


def test_http_error_translated_via_shared_helper(tmp_api_cache: Path,
                                                   monkeypatch: pytest.MonkeyPatch):
    import json as _json

    from googleapiclient.errors import HttpError
    resp = MagicMock(status=403, reason="")
    body = _json.dumps({"error": {
        "message": "quota",
        "errors": [{"reason": "quotaExceeded"}],
    }}).encode("utf-8")
    exc = HttpError(resp, body)

    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = MagicMock()
    client.reports.return_value.query.return_value.execute.side_effect = exc
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        result = my_analytics.get_my_analytics("2026-03-01", "2026-03-02")
    assert result["error"] == "quota_exceeded"


def test_default_metrics_used_when_not_specified(tmp_api_cache: Path,
                                                   monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = _mock_client(rows=[], columns=list(my_analytics.DEFAULT_METRICS))
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        my_analytics.get_my_analytics("2026-03-01", "2026-03-02")

    _, kwargs = client.reports.return_value.query.call_args
    sent_metrics = kwargs["metrics"].split(",")
    assert set(sent_metrics) == set(my_analytics.DEFAULT_METRICS)


def test_channel_id_lowercase_mine_normalized(tmp_api_cache: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    """'mine' and 'me' both map to the 'MINE' alias — avoid a literal-string mishap."""
    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = _mock_client(rows=[])
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        my_analytics.get_my_analytics("2026-03-01", "2026-03-02", channel_id="mine")
    _, kwargs = client.reports.return_value.query.call_args
    assert kwargs["ids"] == "channel==MINE"


def test_channel_id_invalid_value_rejected(tmp_api_cache: Path):
    result = my_analytics.get_my_analytics(
        "2026-03-01", "2026-03-02", channel_id="not-a-channel",
    )
    assert result["error"] == "invalid_channel_id"


def test_cache_key_order_insensitive_for_metrics(tmp_api_cache: Path,
                                                   monkeypatch: pytest.MonkeyPatch):
    """Same metrics in different caller-order must share the cache entry."""
    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = _mock_client()
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        first = my_analytics.get_my_analytics(
            "2026-03-01", "2026-03-02",
            metrics=["views", "impressions"],
        )
    # Second call reorders the same metrics — must hit cache (no rebuild).
    with patch(
        "mcp_server.tools.my_analytics.build",
        side_effect=AssertionError("metrics-order should not invalidate cache"),
    ):
        second = my_analytics.get_my_analytics(
            "2026-03-01", "2026-03-02",
            metrics=["impressions", "views"],
        )
    assert second["cached"] is True
    assert second["rows"] == first["rows"]


def test_custom_channel_id_ids_parameter(tmp_api_cache: Path,
                                           monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oauth, "get_credentials", lambda *_, **__: _fake_creds())
    client = _mock_client(rows=[])
    with patch("mcp_server.tools.my_analytics.build", return_value=client):
        my_analytics.get_my_analytics(
            "2026-03-01", "2026-03-02",
            channel_id="UC" + "a" * 22,
        )
    _, kwargs = client.reports.return_value.query.call_args
    assert kwargs["ids"] == "channel==UC" + "a" * 22
