"""JWT authentication + Google OAuth2 token management."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.config.settings import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


def create_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload["exp"] = expire
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request) -> dict[str, Any] | None:
    """Extract and validate JWT from Authorization header.
    Returns None if no token is provided (allowing unauthenticated access).
    """
    creds: HTTPAuthorizationCredentials | None = await _bearer(request)
    if creds is None:
        return None
    return decode_token(creds.credentials)


def build_google_auth_url() -> str:
    """Build Google OAuth2 authorization URL."""
    if not settings.has_google:
        return ""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join([
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
        ]),
        "access_type": "offline",
        "prompt": "consent",
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"


async def exchange_google_code(code: str) -> dict[str, Any]:
    """Exchange authorization code for tokens."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        tokens = resp.json()
        # Store expiry timestamp for later refresh checks
        if "expires_in" in tokens:
            tokens["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
            ).isoformat()
        return tokens


async def refresh_google_token(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired Google access token."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        tokens = resp.json()
        tokens["refresh_token"] = refresh_token  # Google doesn't always return it
        if "expires_in" in tokens:
            tokens["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
            ).isoformat()
        return tokens


async def get_valid_google_token(db) -> str | None:
    """Get a valid Google access token, refreshing if expired."""
    import json
    from server.database import crud

    state = await crud.get_user_state(db)
    if not state or not state.get("google_token"):
        return None

    try:
        tokens = json.loads(state["google_token"])
    except (json.JSONDecodeError, TypeError):
        return None

    access_token = tokens.get("access_token")
    if not access_token:
        return None

    # Check if expired
    expires_at = tokens.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt < datetime.now(timezone.utc) + timedelta(minutes=5):
                # Token expired or about to expire — refresh
                refresh_token = tokens.get("refresh_token")
                if not refresh_token:
                    logger.warning("Google token expired and no refresh token")
                    return None
                logger.info("Refreshing expired Google token")
                new_tokens = await refresh_google_token(refresh_token)
                await crud.upsert_user_state(db, google_token=json.dumps(new_tokens))
                return new_tokens.get("access_token")
        except (ValueError, TypeError):
            pass

    return access_token
