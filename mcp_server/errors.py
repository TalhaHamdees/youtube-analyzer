"""Shared error-translation helpers.

Google API clients (``googleapiclient``) raise ``HttpError`` whose body encodes
the failure reason. This module maps those to our project-wide error taxonomy
so tools return uniform ``{"error": "<code>", "detail": "..."}`` dicts.
"""
from __future__ import annotations

import json
from typing import Any

from googleapiclient.errors import HttpError


def translate_http_error(exc: HttpError) -> dict[str, Any]:
    """Map googleapiclient HttpError to a structured-error dict.

    Codes produced:
    - ``quota_exceeded`` — 403 + reason ``quotaExceeded``
    - ``rate_limited`` — 429, or 403 + reason ``rateLimitExceeded`` / ``userRateLimitExceeded``
    - ``invalid_api_key`` — 403 + reason ``keyInvalid``
    - ``insufficient_permissions`` — 403 + reason ``insufficientPermissions`` (Analytics API)
    - ``forbidden`` — generic 403
    - ``bad_request`` — 400
    - ``not_found`` — 404
    - ``api_error`` — fallback for anything else
    """
    status = exc.resp.status
    reason = ""
    try:
        content = json.loads(exc.content.decode("utf-8"))
        errors = content.get("error", {}).get("errors") or []
        if errors:
            reason = errors[0].get("reason", "")
        message = content.get("error", {}).get("message", str(exc))
    except (ValueError, AttributeError, UnicodeDecodeError):
        message = str(exc)

    if status == 403 and reason == "quotaExceeded":
        return {"error": "quota_exceeded", "detail": message}
    if status == 429 or reason in ("rateLimitExceeded", "userRateLimitExceeded"):
        return {"error": "rate_limited", "detail": message}
    if status == 403 and reason == "keyInvalid":
        return {"error": "invalid_api_key", "detail": message}
    if status == 403 and reason == "insufficientPermissions":
        return {"error": "insufficient_permissions", "detail": message}
    if status == 403 and reason == "forbidden":
        return {"error": "forbidden", "detail": message}
    if status == 400:
        return {"error": "bad_request", "detail": message}
    if status == 404:
        return {"error": "not_found", "detail": message}
    return {"error": "api_error", "status": status, "detail": message}
