"""Proactive agent - triggers alerts WITHOUT being asked.

THIS IS THE SECOND KEY DIFFERENTIATOR. Unlike ChatGPT/OpenClaw that only respond
when prompted, J.A.R.V.I.S proactively detects situations that need attention:

1. Unreplied emails > 24h (high priority) or > 48h (any priority)
2. Task deadlines within 24h
3. Overdue promises from recordings
4. Late night work (after 22:00) - overtime warning
5. Long idle during work hours - well-being check
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.agents.base import BaseAgent, call_llm, extract_text
from server.database import crud

logger = logging.getLogger(__name__)

# Cooldown: don't repeat the same alert type within this window
COOLDOWN_HOURS = {
    "email_remind": 4,
    "deadline": 2,
    "promise_overdue": 8,
    "overtime": 2,
    "idle_check": 3,
}


async def _in_cooldown(db: aiosqlite.Connection, alert_type: str) -> bool:
    """Check if this alert type was recently sent."""
    hours = COOLDOWN_HOURS.get(alert_type, 4)
    # Use both ISO and SQLite datetime formats for compatibility
    since_utc = (datetime.now(timezone.utc) - timedelta(hours=hours))
    since_iso = since_utc.isoformat()
    since_sqlite = since_utc.strftime("%Y-%m-%d %H:%M:%S")
    recent = await crud.get_recent_notifications(db, type=alert_type, since=since_sqlite)
    if not recent:
        recent = await crud.get_recent_notifications(db, type=alert_type, since=since_iso)
    return len(recent) > 0


async def check_unreplied_emails(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Emails unreplied for too long."""
    alerts = []
    unreplied = await crud.get_unreplied_emails(db, limit=50)
    now = datetime.now(timezone.utc)

    for email in unreplied:
        received = email.get("received_at", "")
        try:
            received_dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        hours_ago = (now - received_dt).total_seconds() / 3600
        priority = email.get("priority", "normal")

        # High priority: alert after 1h. Normal: after 4h.
        threshold = 1 if priority == "high" else 4
        if hours_ago >= threshold:
            alerts.append({
                "type": "email_remind",
                "title": f"미답장 메일 ({int(hours_ago)}시간 경과)",
                "message": f"'{email['subject']}' (from {email['sender']}) - {int(hours_ago)}시간 전 수신, 아직 답장하지 않았습니다.",
                "reference_id": email.get("id"),
            })
    return alerts


async def check_upcoming_deadlines(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Tasks due within 24 hours."""
    alerts = []
    tasks = await crud.get_tasks(db, status="pending", limit=50)
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=24)

    for task in tasks:
        due = task.get("due_date")
        if not due:
            continue
        try:
            due_dt = datetime.fromisoformat(due)
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if now <= due_dt <= deadline:
            hours_left = (due_dt - now).total_seconds() / 3600
            alerts.append({
                "type": "deadline",
                "title": f"마감 임박 ({int(hours_left)}시간 남음)",
                "message": f"'{task['title']}' 마감이 {int(hours_left)}시간 후입니다.",
                "reference_id": task.get("id"),
            })
    return alerts


async def check_overdue_promises(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Promises from recordings that are past due."""
    alerts = []
    pending = await crud.get_promises(db, status="pending", limit=50)
    now = datetime.now(timezone.utc)

    for p in pending:
        due = p.get("due_date")
        if not due:
            continue
        try:
            due_dt = datetime.fromisoformat(due)
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if due_dt < now:
            # Auto-update status to overdue
            await crud.update_promise_status(db, p["id"], "overdue")
            days_overdue = (now - due_dt).days
            alerts.append({
                "type": "promise_overdue",
                "title": f"약속 지연 ({days_overdue}일 초과)",
                "message": f"'{p['content']}' - 마감일({due})이 {days_overdue}일 지났습니다.",
                "reference_id": p.get("id"),
            })
    return alerts


async def check_overtime(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Working past 22:00 local time (based on PC activity)."""
    alerts = []
    now = datetime.now(timezone.utc)
    # Check if there's recent PC activity and it's late
    local_hour = (now + timedelta(hours=9)).hour  # KST = UTC+9

    if local_hour >= 22 or local_hour < 5:
        # Check for PC activity in the last 30 min
        since = (now - timedelta(minutes=30)).isoformat()
        recent_pc = await crud.get_pc_activity(db, since=since, limit=5)
        active = [r for r in recent_pc if not r.get("idle")]
        if active:
            alerts.append({
                "type": "overtime",
                "title": "야근 감지",
                "message": f"현재 시각 {(local_hour):02d}시입니다. 아직 PC 활동이 감지됩니다. 오늘은 이만 쉬는 것은 어떨까요?",
            })
    return alerts


async def run_proactive_check(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Run all proactive checks and return new alerts (respecting cooldowns)."""
    all_alerts = []

    checkers = [
        check_unreplied_emails,
        check_upcoming_deadlines,
        check_overdue_promises,
        check_overtime,
    ]

    for checker in checkers:
        try:
            alerts = await checker(db)
            for alert in alerts:
                alert_type = alert["type"]
                if await _in_cooldown(db, alert_type):
                    continue
                # Save to DB
                nid = await crud.insert_notification(
                    db,
                    type=alert["type"],
                    title=alert["title"],
                    message=alert["message"],
                    reference_id=alert.get("reference_id"),
                )
                alert["id"] = nid
                all_alerts.append(alert)
        except Exception:
            logger.exception("Proactive check failed: %s", checker.__name__)

    if all_alerts:
        logger.info("Proactive check generated %d new alerts", len(all_alerts))
    return all_alerts


class ProactiveAgent(BaseAgent):
    name = "proactive"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        """Generate a natural language summary of proactive alerts."""
        db = context.get("db")
        if db is None:
            return "DB connection required."

        alerts = await run_proactive_check(db)
        if not alerts:
            return "현재 특별히 챙길 것이 없습니다."

        # Use Claude to generate a natural summary
        alert_text = "\n".join(
            f"- [{a['type']}] {a['title']}: {a['message']}" for a in alerts
        )
        messages = [
            {"role": "user", "content": f"다음 프로액티브 알림들을 자연스러운 한국어로 요약해 주세요:\n\n{alert_text}"},
        ]
        system = "당신은 J.A.R.V.I.S 비서입니다. 프로액티브 알림을 간결하고 자연스럽게 전달하세요. 이모지 사용하지 마세요."
        response = await call_llm(messages, tier="light", system=system)
        return extract_text(response)
