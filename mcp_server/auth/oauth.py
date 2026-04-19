"""Google OAuth 2.0 flow for YouTube Analytics own-channel access.

Reads ``OAUTH_CLIENT_ID`` / ``OAUTH_CLIENT_SECRET`` from env, caches the granted
token at ``data/cache/oauth/token.json``. First call opens a browser consent
screen; subsequent calls reuse (and silently refresh) the cached token.

Client secrets live only in env — never on disk — so there is no
``client_secrets.json`` to leak into git.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from mcp_server import paths

_log = logging.getLogger(__name__)

DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
)
# For monetary metrics (estimated revenue) add:
#   "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"

_dotenv_loaded = False


def _load_env() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    env_path = paths.PROJECT_ROOT / "config" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _dotenv_loaded = True


def _client_config() -> dict[str, Any] | None:
    _load_env()
    cid = os.environ.get("OAUTH_CLIENT_ID", "").strip()
    secret = os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    return {
        "installed": {
            "client_id": cid,
            "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _token_path() -> Path:
    # Resolve at call time so test monkeypatches of ``paths`` apply.
    return paths.OAUTH_CACHE / "token.json"


def _load_cached(scopes: tuple[str, ...]) -> Credentials | None:
    """Load the cached token — ONLY if its granted scopes cover all requested.

    ``Credentials.from_authorized_user_info`` records the caller-requested
    scopes on the returned object but does not verify them against the token's
    actual grant; a narrower-than-requested token would silently produce
    ``insufficientPermissions`` on the first API call. We do the check here
    explicitly and force a re-auth on mismatch.
    """
    token_file = _token_path()
    if not token_file.exists():
        return None
    try:
        info = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _log.warning("oauth token cache unreadable at %s — reauth required", token_file)
        return None

    granted = set(info.get("scopes") or [])
    if granted and not set(scopes).issubset(granted):
        _log.info(
            "oauth cached token scopes %s do not cover requested %s — reauth",
            sorted(granted), sorted(scopes),
        )
        return None

    try:
        return Credentials.from_authorized_user_info(info, scopes=list(scopes))
    except ValueError:
        return None


def _save(creds: Credentials) -> None:
    paths.ensure(paths.OAUTH_CACHE)
    token_file = _token_path()
    tmp = token_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(creds.to_json(), encoding="utf-8")
        os.replace(tmp, token_file)
        # Best-effort restriction to owner r/w (0600). No-op on Windows; on
        # POSIX filesystems this matters — the file carries a refresh token.
        try:
            os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except OSError as exc:
        _log.warning("oauth token save failed: %s", exc)


def _clear_cache() -> None:
    token_file = _token_path()
    try:
        token_file.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log.warning("oauth token clear failed: %s", exc)


def get_credentials(
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    *,
    force_reauth: bool = False,
    open_browser: bool = True,
) -> Credentials | dict[str, Any]:
    """Return valid Google OAuth2 credentials, running the browser flow if needed.

    Returns a ``Credentials`` object on success, or a structured error dict
    (``{"error": "...", "detail": "..."}``) when the client is not configured
    or the flow cannot run headlessly.

    On ``force_reauth=True`` the cached token file is deleted *before* the
    new flow runs — so a user canceling the browser consent doesn't leave
    stale credentials on disk.
    """
    config = _client_config()
    if config is None:
        return {
            "error": "oauth_not_configured",
            "detail": ("set OAUTH_CLIENT_ID + OAUTH_CLIENT_SECRET in config/.env "
                       "— see config/.env.example"),
        }

    if force_reauth:
        _clear_cache()

    creds: Credentials | None = None if force_reauth else _load_cached(scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except RefreshError as exc:
            # Refresh token was revoked or the grant was removed — clear the
            # cache and fall through to the browser flow.
            _log.info("oauth refresh_token rejected (%s) — clearing cache", exc)
            _clear_cache()
            creds = None
        except Exception as exc:  # noqa: BLE001
            # Transient (network, clock skew) — attempt browser flow.
            _log.info("oauth refresh errored (%s) — falling through to flow", exc)
            creds = None

    if not open_browser:
        return {
            "error": "oauth_reauth_required",
            "detail": ("cached token missing/expired/scope-insufficient and "
                       "open_browser=False; call interactively with "
                       "open_browser=True to re-grant"),
        }

    flow = InstalledAppFlow.from_client_config(config, list(scopes))
    creds = flow.run_local_server(port=0)
    _save(creds)
    return creds


def _reset_for_tests() -> None:
    global _dotenv_loaded
    _dotenv_loaded = False
