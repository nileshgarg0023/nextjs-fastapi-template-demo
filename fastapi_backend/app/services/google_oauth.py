import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.config import settings

GMAIL_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def build_google_oauth_url(user_id: str) -> str:
    _require_google_oauth_settings()
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GMAIL_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": create_oauth_state(user_id),
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def create_oauth_state(user_id: str) -> str:
    payload = {"user_id": user_id, "iat": int(time.time())}
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = _urlsafe_b64encode(payload_json)
    signature = hmac.new(
        settings.ACCESS_SECRET_KEY.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_urlsafe_b64encode(signature)}"


def parse_oauth_state(state: str) -> str:
    try:
        encoded_payload, encoded_signature = state.split(".", maxsplit=1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        ) from exc

    expected_signature = hmac.new(
        settings.ACCESS_SECRET_KEY.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual_signature = _urlsafe_b64decode(encoded_signature)

    if not hmac.compare_digest(expected_signature, actual_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state signature.",
        )

    payload = json.loads(_urlsafe_b64decode(encoded_payload).decode("utf-8"))
    if int(time.time()) - int(payload["iat"]) > 900:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state expired.",
        )
    return payload["user_id"]


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    _require_google_oauth_settings()
    return _post_google_token(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        }
    )


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    _require_google_oauth_settings()
    return _post_google_token(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )


def _post_google_token(body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google OAuth token exchange failed: {_read_error_detail(exc)}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google OAuth token exchange could not be completed.",
        ) from exc


def _require_google_oauth_settings() -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth client ID and secret are not configured.",
        )


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _read_error_detail(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return body.get("error_description") or body.get("error") or exc.reason
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return exc.reason
