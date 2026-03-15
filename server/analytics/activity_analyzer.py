"""Aggregates app/program usage time by category and period.

Combines mobile app_usage + PC pc_activity data to produce a unified view.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.database import crud


def _today_range() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


async def get_daily_summary(
    db: aiosqlite.Connection,
    date: str | None = None,
) -> dict[str, Any]:
    """Full daily activity summary across mobile + PC.

    Returns: {
        date, total_active_s, mobile: {total_s, apps: [...]},
        pc: {total_s, apps: [...]},
        top_apps: [...], unreplied_emails: int,
        pending_promises: int, upcoming_events: int
    }
    """
    if date:
        since = f"{date}T00:00:00"
        until = f"{date}T23:59:59"
    else:
        since, until = _today_range()

    mobile_apps = await crud.get_app_usage_summary(db, since=since, until=until, device="mobile")
    pc_apps = await crud.get_pc_activity_summary(db, since=since, until=until)

    mobile_total = sum(a.get("total_seconds") or 0 for a in mobile_apps)
    pc_total = sum(a.get("total_seconds") or 0 for a in pc_apps)

    # Merge into unified top-apps list
    all_apps: list[dict[str, Any]] = []
    for a in mobile_apps:
        all_apps.append({
            "name": a["app"],
            "device": "mobile",
            "seconds": a.get("total_seconds") or 0,
            "sessions": a.get("sessions") or 0,
        })
    for a in pc_apps:
        all_apps.append({
            "name": a.get("process_name") or "unknown",
            "device": "pc",
            "seconds": a.get("total_seconds") or 0,
            "sessions": a.get("sessions") or 0,
        })
    all_apps.sort(key=lambda x: x["seconds"], reverse=True)

    unreplied = await crud.get_unreplied_emails(db, limit=100)
    promises = await crud.get_promises(db, status="pending")
    events = await crud.get_upcoming_events(db, since=since, until=until)

    # Include screen_texts summary for richer "what did I do" answers
    screen_texts = await crud.get_screen_texts(db, since=since, limit=50)
    visited_sites: list[dict[str, Any]] = []
    seen = set()
    for st in screen_texts:
        app = st.get("app_name", "")
        title = (st.get("window_title") or "")[:60]
        key = f"{app}|{title}"
        if key not in seen:
            seen.add(key)
            visited_sites.append({
                "app": app,
                "title": title,
                "text_preview": (st.get("extracted_text") or "")[:150],
                "time": (st.get("timestamp") or "")[:16],
            })

    return {
        "date": date or since[:10],
        "total_active_s": mobile_total + pc_total,
        "mobile": {"total_s": mobile_total, "apps": mobile_apps[:10]},
        "pc": {"total_s": pc_total, "apps": pc_apps[:10]},
        "top_apps": all_apps[:10],
        "visited_sites": visited_sites[:15],
        "unreplied_emails": len(unreplied),
        "pending_promises": len(promises),
        "upcoming_events": len(events),
    }


async def get_period_trend(
    db: aiosqlite.Connection,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Daily activity totals for the last N days."""
    now = datetime.now(timezone.utc)
    trend = []
    for i in range(days):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        summary = await get_daily_summary(db, date=day)
        trend.append({
            "date": day,
            "total_active_s": summary["total_active_s"],
            "mobile_s": summary["mobile"]["total_s"],
            "pc_s": summary["pc"]["total_s"],
        })
    trend.reverse()
    return trend


def format_duration(seconds: int) -> str:
    """Human-readable duration string."""
    if seconds < 60:
        return f"{seconds}초"
    if seconds < 3600:
        return f"{seconds // 60}분"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"
