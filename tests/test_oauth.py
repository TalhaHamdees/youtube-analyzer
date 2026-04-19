"""Tests for mcp_server.auth.oauth — all network/browser interaction mocked."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError

from mcp_server import paths
from mcp_server.auth import oauth


@pytest.fixture
def tmp_oauth_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = tmp_path / "oauth"
    monkeypatch.setattr(paths, "OAUTH_CACHE", cache)
    return cache


@pytest.fixture(autouse=True)
def _reset_oauth(monkeypatch: pytest.MonkeyPatch):
    oauth._reset_for_tests()
    # Default: creds configured. Individual tests that need the unconfigured
    # path delete these.
    monkeypatch.setenv("OAUTH_CLIENT_ID", "fake-cid.apps.googleusercontent.com")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(paths, "PROJECT_ROOT", Path("/__no_real_env__"))
    yield
    oauth._reset_for_tests()


def _fake_creds(valid: bool = True, expired: bool = False,
                refresh_token: str | None = "fake-refresh") -> MagicMock:
    creds = MagicMock(spec=oauth.Credentials)
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = refresh_token
    creds.to_json.return_value = json.dumps({
        "token": "fake-access",
        "refresh_token": refresh_token,
        "client_id": "cid",
        "client_secret": "sec",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    return creds


def test_missing_oauth_env_returns_structured_error(
    tmp_oauth_cache: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OAUTH_CLIENT_ID")
    monkeypatch.delenv("OAUTH_CLIENT_SECRET")
    result = oauth.get_credentials()
    assert isinstance(result, dict)
    assert result["error"] == "oauth_not_configured"


def test_first_call_runs_browser_flow_and_saves_token(tmp_oauth_cache: Path):
    fake = _fake_creds()
    flow = MagicMock()
    flow.run_local_server.return_value = fake
    with patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ) as m_build:
        result = oauth.get_credentials()
    assert result is fake
    m_build.assert_called_once()
    flow.run_local_server.assert_called_once_with(port=0)
    token_file = tmp_oauth_cache / "token.json"
    assert token_file.exists()
    # The saved token must be structurally valid JSON with key fields preserved.
    on_disk = json.loads(token_file.read_text(encoding="utf-8"))
    assert on_disk["token"] == "fake-access"
    assert on_disk["refresh_token"] == "fake-refresh"


def test_second_call_reuses_cached_valid_token(tmp_oauth_cache: Path):
    # Seed a valid token on disk.
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    (tmp_oauth_cache / "token.json").write_text(json.dumps({
        "token": "seed", "refresh_token": "rt",
        "client_id": "cid", "client_secret": "sec",
        "token_uri": "https://oauth2.googleapis.com/token",
    }), encoding="utf-8")

    fake = _fake_creds(valid=True)
    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
        return_value=fake,
    ), patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
    ) as m_flow:
        result = oauth.get_credentials()
    assert result is fake
    m_flow.assert_not_called()


def test_expired_token_refreshes_silently(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    (tmp_oauth_cache / "token.json").write_text("{}", encoding="utf-8")

    fake = _fake_creds(valid=False, expired=True, refresh_token="rt")
    # After .refresh(), creds become valid — simulate via side effect.
    def _refresh_side_effect(*_a, **_k):
        fake.valid = True

    fake.refresh.side_effect = _refresh_side_effect

    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
        return_value=fake,
    ), patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
    ) as m_flow:
        result = oauth.get_credentials()
    assert result is fake
    assert fake.valid is True
    fake.refresh.assert_called_once()
    m_flow.assert_not_called()


def test_revoked_refresh_token_clears_cache_and_reauths(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    token_file = tmp_oauth_cache / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    expired = _fake_creds(valid=False, expired=True, refresh_token="revoked")
    expired.refresh.side_effect = RefreshError("invalid_grant")

    fresh = _fake_creds(valid=True)
    flow = MagicMock()
    flow.run_local_server.return_value = fresh

    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
        return_value=expired,
    ), patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        result = oauth.get_credentials()
    assert result is fresh
    flow.run_local_server.assert_called_once()


def test_scope_widening_forces_reauth(tmp_oauth_cache: Path):
    """If requested scopes exceed what the cached token grants, reauth must run."""
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    token_file = tmp_oauth_cache / "token.json"
    # Seed a token granted only for the youtube.readonly scope.
    token_file.write_text(json.dumps({
        "token": "narrow",
        "refresh_token": "rt",
        "client_id": "cid",
        "client_secret": "sec",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
    }), encoding="utf-8")

    fresh = _fake_creds(valid=True)
    flow = MagicMock()
    flow.run_local_server.return_value = fresh
    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
    ) as m_load, patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        # Default scopes include yt-analytics.readonly too → mismatch → reauth.
        result = oauth.get_credentials()
    assert result is fresh
    m_load.assert_not_called()  # rejected before hydrating Credentials


def test_force_reauth_deletes_token_before_flow(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    token_file = tmp_oauth_cache / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    fresh = _fake_creds()
    flow = MagicMock()
    # Simulate: the flow verifies the token file is gone at the moment it runs.
    def _run_and_check(*_a, **_k):
        assert not token_file.exists(), "force_reauth must delete stale token first"
        return fresh
    flow.run_local_server.side_effect = _run_and_check

    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
    ) as m_load, patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        result = oauth.get_credentials(force_reauth=True)
    assert result is fresh
    m_load.assert_not_called()
    # After the flow completes the fresh creds have been saved.
    assert token_file.exists()


def test_refresh_failure_falls_back_to_browser(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    (tmp_oauth_cache / "token.json").write_text("{}", encoding="utf-8")

    expired = _fake_creds(valid=False, expired=True, refresh_token="rt")
    expired.refresh.side_effect = RuntimeError("refresh server error")

    fresh = _fake_creds(valid=True)
    flow = MagicMock()
    flow.run_local_server.return_value = fresh

    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
        return_value=expired,
    ), patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        result = oauth.get_credentials()
    assert result is fresh
    flow.run_local_server.assert_called_once()


def test_open_browser_false_without_cache_returns_reauth_error(tmp_oauth_cache: Path):
    result = oauth.get_credentials(open_browser=False)
    assert result["error"] == "oauth_reauth_required"


def test_force_reauth_ignores_existing_cache(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    (tmp_oauth_cache / "token.json").write_text("{}", encoding="utf-8")

    fresh = _fake_creds()
    flow = MagicMock()
    flow.run_local_server.return_value = fresh

    with patch(
        "mcp_server.auth.oauth.Credentials.from_authorized_user_info",
        return_value=_fake_creds(valid=True),  # would satisfy normally
    ) as m_load, patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        result = oauth.get_credentials(force_reauth=True)
    assert result is fresh
    m_load.assert_not_called()  # cache load skipped entirely


def test_corrupt_token_cache_triggers_reauth(tmp_oauth_cache: Path):
    tmp_oauth_cache.mkdir(parents=True, exist_ok=True)
    (tmp_oauth_cache / "token.json").write_text("not-json{{", encoding="utf-8")

    fresh = _fake_creds()
    flow = MagicMock()
    flow.run_local_server.return_value = fresh

    with patch(
        "mcp_server.auth.oauth.InstalledAppFlow.from_client_config",
        return_value=flow,
    ):
        result = oauth.get_credentials()
    assert result is fresh
