"""Syncs Google Calendar events for schedule awareness.

Requires Google OAuth credentials. Provides mock data when unavailable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.config.settings import settings
from server.database import crud

logger = logging.getLogger(__name__)


async def _fetch_events_google(
    token: str, time_min: str, time_max: str, max_results: int = 50
) -> list[dict[str, Any]]:
    """Fetch calendar events via Google Calendar API."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])

    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        attendees = [a.get("email", "") for a in item.get("attendees", [])]
        events.append({
            "google_event_id": item["id"],
            "title": item.get("summary", "(제목 없음)"),
            "description": item.get("description"),
            "start_time": start.get("dateTime", start.get("date", "")),
            "end_time": end.get("dateTime", end.get("date", "")),
            "location": item.get("location"),
            "attendees": json.dumps(attendees) if attendees else None,
            "status": item.get("status", "confirmed"),
        })
    return events


def _mock_events() -> list[dict[str, Any]]:
    """Return mock calendar events for development."""
    now = datetime.now(timezone.utc)
    today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return [
        {
            "google_event_id": "mock_evt_001",
            "title": "팀 스탠드업",
            "description": "일일 스탠드업 미팅",
            "start_time": today_9am.isoformat(),
            "end_time": (today_9am + timedelta(minutes=30)).isoformat(),
            "location": "회의실 A",
            "attendees": json.dumps(["team@company.com"]),
            "status": "confirmed",
        },
        {
            "google_event_id": "mock_evt_002",
            "title": "1:1 미팅 with 팀장",
            "description": None,
            "start_time": (today_9am + timedelta(hours=2)).isoformat(),
            "end_time": (today_9am + timedelta(hours=2, minutes=30)).isoformat(),
            "location": None,
            "attendees": json.dumps(["manager@company.com"]),
            "status": "confirmed",
        },
        {
            "google_event_id": "mock_evt_003",
            "title": "프로젝트 리뷰",
            "description": "Q1 프로젝트 진행 상황 리뷰",
            "start_time": (today_9am + timedelta(hours=5)).isoformat(),
            "end_time": (today_9am + timedelta(hours=6)).isoformat(),
            "location": "대회의실",
            "attendees": json.dumps(["team@company.com", "director@company.com"]),
            "status": "confirmed",
        },
    ]


async def sync_calendar(
    db: aiosqlite.Connection,
    google_token: str | None = None,
    days_ahead: int = 7,
) -> dict[str, int]:
    """Sync calendar events to local DB."""
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    if google_token and settings.has_google:
        try:
            events = await _fetch_events_google(google_token, time_min, time_max)
        except Exception:
            logger.exception("Calendar API fetch failed, using mock data")
            events = _mock_events()
    else:
        logger.info("Google credentials not configured, using mock calendar data")
        events = _mock_events()

    synced = 0
    for e in events:
        await crud.upsert_calendar_event(db, **e)
        synced += 1

    logger.info("Calendar sync complete: %d events", synced)
    return {"synced": synced}
