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
    "meeting_soon": 0.5,  # 30 min
    "evening_briefing": 12,
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
    """Emails unreplied for too long — with reply draft."""
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

        threshold = 1 if priority == "high" else 4
        if hours_ago >= threshold:
            subject = email["subject"]
            # Generate a short reply draft based on subject
            draft = _generate_reply_draft(subject)

            if hours_ago >= 48:
                tone = f"'{subject}' 답장 {int(hours_ago)}시간째 안 하셨습니다. 놓치시면 안 돼요. 초안: \"{draft}\" — 보낼까요?"
            elif hours_ago >= 12:
                tone = f"'{subject}' 답장 아직인데, 짧게라도 보낼까요? 초안: \"{draft}\""
            else:
                tone = f"'{subject}' {int(hours_ago)}시간 전 수신. 회신 필요합니다."
            alerts.append({
                "type": "email_remind",
                "title": f"미답장 메일 ({int(hours_ago)}시간 경과)",
                "message": tone,
                "reference_id": email.get("id"),
            })
    return alerts


def _generate_reply_draft(subject: str) -> str:
    """Generate a 1-line reply draft based on email subject."""
    s = subject.lower()
    if "요청" in s or "부탁" in s:
        return "요청 건 확인했습니다. 검토 후 회신드리겠습니다."
    if "확인" in s or "조회" in s:
        return "확인했습니다. 처리 후 안내드리겠습니다."
    if "세금계산서" in s or "발행" in s:
        return "세금계산서 발행 건 접수했습니다. 처리 후 보고드리겠습니다."
    if "io코드" in s or "발주" in s:
        return "IO코드 건 확인했습니다. 생성 후 전달드리겠습니다."
    if "보고" in s or "검토" in s:
        return "검토 중입니다. 완료 후 회신드리겠습니다."
    return "확인했습니다. 검토 후 회신드리겠습니다."
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
            title = task["title"]
            if hours_left <= 4:
                tone = f"'{title}' — {int(hours_left)}시간 남았습니다. 지금 시작하셔야 해요."
            elif hours_left <= 12:
                tone = f"'{title}' — 오늘 안에 마감입니다. 오후에 시간 내서 처리하시면 됩니다."
            else:
                tone = f"'{title}' — 내일 마감입니다. 오늘 중으로 준비해두시면 좋겠습니다."
            alerts.append({
                "type": "deadline",
                "title": "마감 임박",
                "message": tone,
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
                "message": f"지금 {local_hour}시입니다. 오늘 많이 하셨으니 나머지는 내일 하셔도 됩니다.",
            })
    return alerts


async def check_upcoming_meetings(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Meeting starting within 30 minutes — remind with context."""
    alerts = []
    now = datetime.now(timezone.utc)
    window = now + timedelta(minutes=30)

    events = await crud.get_upcoming_events(
        db, since=now.isoformat(), until=window.isoformat()
    )
    for ev in events:
        title = ev.get("title", "회의")
        start = ev.get("start_time", "")[:16]
        location = ev.get("location") or ""
        loc_str = f" ({location})" if location else ""

        # Try to find related screen_texts for context
        context_hint = ""
        try:
            texts = await crud.get_screen_texts(db, limit=20)
            keywords = title.lower().split()
            for t in texts:
                text_lower = (t.get("extracted_text") or "").lower()
                if any(kw in text_lower for kw in keywords if len(kw) > 2):
                    context_hint = f" 최근에 관련 자료를 확인하셨으니 준비해가세요."
                    break
        except Exception:
            pass

        alerts.append({
            "type": "meeting_soon",
            "title": f"회의 30분 전",
            "message": f"'{title}' {start}{loc_str} — 30분 남았습니다.{context_hint}",
        })
    return alerts


async def check_end_of_day(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """18:00 KST — auto-generate evening briefing."""
    alerts = []
    now = datetime.now(timezone.utc)
    local_hour = (now + timedelta(hours=9)).hour

    if local_hour == 18:
        from server.agents.briefing import BriefingAgent
        try:
            agent = BriefingAgent()
            context = {"db": db, "locale": "ko"}
            content = await agent.generate_briefing(context, briefing_type="evening")
            alerts.append({
                "type": "evening_briefing",
                "title": "퇴근 브리핑",
                "message": content[:500],
            })
        except Exception:
            logger.exception("Auto evening briefing failed")
    return alerts


async def run_proactive_check(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Run all proactive checks and return new alerts (respecting cooldowns)."""
    all_alerts = []

    checkers = [
        check_unreplied_emails,
        check_upcoming_deadlines,
        check_overdue_promises,
        check_upcoming_meetings,
        check_end_of_day,
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
        system = "당신은 윤정훈님의 전담 비서입니다. 알림을 비서가 슬쩍 말해주듯 전달하세요. 인사 없이 바로 본론. 이모지 없음."
        response = await call_llm(messages, tier="light", system=system)
        return extract_text(response)
