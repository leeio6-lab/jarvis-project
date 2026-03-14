"""Manages conversation context and user state for agent calls."""

from __future__ import annotations

from typing import Any

import aiosqlite

from server.analytics.activity_analyzer import get_daily_summary
from server.database import crud


async def build_context(
    db: aiosqlite.Connection,
    *,
    history: list[dict[str, str]] | None = None,
    locale: str = "ko",
) -> dict[str, Any]:
    """Build the context dict passed to agents."""
    user_state = await crud.get_user_state(db)

    context: dict[str, Any] = {
        "db": db,
        "locale": locale,
        "history": history or [],
        "user_state": user_state,
    }

    # Build a short summary of user's current state for chat context
    try:
        daily = await get_daily_summary(db)
        unreplied = await crud.get_unreplied_emails(db, limit=5)
        pending = await crud.get_promises(db, status="pending")

        summary_parts = []
        if daily.get("total_active_s"):
            summary_parts.append(f"오늘 활동 시간: {daily['total_active_s'] // 60}분")
        if unreplied:
            summary_parts.append(f"미답장 이메일: {len(unreplied)}건")
        if pending:
            summary_parts.append(f"대기 중인 약속: {len(pending)}건")

        context["user_summary"] = " | ".join(summary_parts) if summary_parts else ""
    except Exception:
        context["user_summary"] = ""

    return context
