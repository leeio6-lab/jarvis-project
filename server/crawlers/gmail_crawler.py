"""Crawls Gmail for unreplied emails and tracks reply status.

Requires Google OAuth credentials. When credentials are not available,
provides mock data for development/testing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from server.config.settings import settings
from server.database import crud

logger = logging.getLogger(__name__)


async def _fetch_emails_google(token: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Fetch recent emails via Gmail API."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"maxResults": max_results, "q": "is:inbox"},
            timeout=30.0,
        )
        resp.raise_for_status()
        message_ids = [m["id"] for m in resp.json().get("messages", [])]

        emails = []
        for mid in message_ids:
            detail = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                timeout=30.0,
            )
            detail.raise_for_status()
            data = detail.json()
            headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
            labels = data.get("labelIds", [])
            emails.append({
                "gmail_id": mid,
                "subject": headers.get("Subject", "(no subject)"),
                "sender": headers.get("From", "unknown"),
                "received_at": headers.get("Date", ""),
                "replied": "SENT" in labels or "REPLIED" in str(labels),
            })
    return emails


def _mock_emails() -> list[dict[str, Any]]:
    """Return mock email data for development without Google credentials."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "gmail_id": "mock_001",
            "subject": "Q1 보고서 검토 요청",
            "sender": "boss@company.com",
            "received_at": now,
            "replied": False,
            "priority": "high",
        },
        {
            "gmail_id": "mock_002",
            "subject": "팀 회식 장소 투표",
            "sender": "hr@company.com",
            "received_at": now,
            "replied": False,
            "priority": "normal",
        },
        {
            "gmail_id": "mock_003",
            "subject": "Re: API 연동 건",
            "sender": "dev@partner.com",
            "received_at": now,
            "replied": True,
            "priority": "normal",
        },
    ]


async def sync_emails(
    db: aiosqlite.Connection,
    google_token: str | None = None,
    max_results: int = 20,
) -> dict[str, int]:
    """Sync Gmail emails to local DB. Returns counts of new/updated emails."""
    if google_token and settings.has_google:
        try:
            emails = await _fetch_emails_google(google_token, max_results)
        except Exception:
            logger.exception("Gmail API fetch failed — skipping (no mock in connected mode)")
            emails = []
    else:
        logger.info("Google credentials not configured, using mock email data")
        emails = _mock_emails()

    new_count = 0
    for e in emails:
        await crud.upsert_email(
            db,
            gmail_id=e["gmail_id"],
            subject=e["subject"],
            sender=e["sender"],
            received_at=e["received_at"],
            replied=e.get("replied", False),
            replied_at=e.get("replied_at"),
            priority=e.get("priority", "normal"),
        )
        new_count += 1

    unreplied = await crud.get_unreplied_emails(db)
    logger.info("Email sync complete: %d processed, %d unreplied", new_count, len(unreplied))
    return {"processed": new_count, "unreplied": len(unreplied)}
