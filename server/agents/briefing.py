"""Briefing agent — generates comprehensive briefings from ALL crawled data sources.

THIS IS THE KEY DIFFERENTIATOR from ChatGPT Pulse or other AI assistants.
Unlike services that only read calendar + email, J.A.R.V.I.S synthesizes:
  - Mobile app usage time (어떤 앱을 얼마나 사용했는지)
  - PC activity tracking (어떤 프로그램/웹사이트를 사용했는지)
  - Recording transcripts + summaries (녹음 전사 내용)
  - Promise tracking (약속 이행 추적)
  - Unreplied emails (미답장 이메일 추적)
  - Calendar events (일정)
  - Location history (위치 기록)
  - Productivity analysis (생산성 분석)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.agents.base import BaseAgent, call_llm, extract_text
from server.analytics.activity_analyzer import format_duration, get_daily_summary
from server.database import crud

logger = logging.getLogger(__name__)

MORNING_SYSTEM = """당신은 윤정훈님의 전담 비서입니다. 월 300만원 받는 비서처럼 아침 보고하세요.

## 형식 — 바로 본론. 인사 없이 시작.

[긴급]
- 미답장 메일 중 24시간 지난 것을 맨 위에. "임상민님 메일 — 어제 14시 수신, 아직 답장 안 하셨습니다."
- 마감 오늘/내일인 할 일. "월간 보고서 — 오늘 마감입니다."

[오늘 일정]
- 시간순. "09:00 팀 스탠드업 (회의실 A) / 11:00 팀장 1:1 / 14:00 프로젝트 리뷰 (대회의실)"

[오늘 하실 것]
- 3가지. "무엇을 하라"가 아니라 "어떻게 하면 되는지"까지.
- 나쁜 예: "월간 보고서 작성"
- 좋은 예: "월간 보고서 — 어제 SAP에서 고정자산 데이터 확인하셨으니 AS01 기준으로 정리하시면 됩니다"
- screen_texts에서 어제 무슨 작업을 했는지 보고, 그걸 연결해서 제안

[어제 요약]
- 한 줄. "SAP 2h32m, Excel 1h, 카톡 45m"

## 톤
- 비서가 보고하는 톤. "~입니다", "~하셨습니다"
- 인사, 응원, 마무리 멘트 전부 빼기. 낭비.
- 구체적 이름/숫자 필수. "메일 N건" 말고 "임상민님 세액공제 건, 엠서클 세금계산서 건"
- 없는 항목은 섹션째 생략. "없습니다" 쓰지 마.
- 이모지 없음. 총 15줄 이내."""

EVENING_SYSTEM = """당신은 윤정훈님의 전담 비서입니다. 퇴근 전 하루 마무리 보고.

## 형식 — 3개 섹션만. 인사/응원 없이 바로.

[오늘 처리한 것]
- 실제로 한 업무만. screen_texts에서 방문한 업무 사이트 기반.
- "SAP 고정자산 등록 방법 조사, DART에서 감사보고서 확인, 홈택스 세금계산서 발행 절차 확인"

[내일로 넘어간 것]
- 미답장 메일 중 중요한 것. "임상민님 세액공제 건 — 내일 오전에 회신하세요"
- 미완료 할 일. "월간 보고서 — 내일 마감"
- 비업무 활동이 있었으면 언급. "쿠팡, 유튜브 이용함"

[까먹으면 안 되는 것]
- 내일 일정 중 준비가 필요한 것
- 48시간 넘긴 미답장
- 이번 주 마감 할 일

## 톤
- 짧고 직접적. "~입니다"
- 없는 항목은 섹션째 생략
- 이모지 없음. 총 10줄 이내."""

SCREEN_SUMMARY_SYSTEM = """전사된 화면 텍스트들을 3~5줄로 요약하세요.
앱별로 사용자가 무엇을 했는지 핵심만 추출합니다.
예: "네이버 웍스에서 김부장 메일 확인 (미답장)", "SAP 고정자산 화면에서 작업"
JSON이 아닌 자연어로. 한국어."""


async def _summarize_screen_texts(screen_texts: list[dict]) -> str:
    """Summarize day's screen texts with Haiku (cheap) before feeding to Sonnet."""
    if not screen_texts:
        return ""

    # Build compact input: app + title + first 200 chars of text
    entries = []
    for st in screen_texts[:20]:
        app = st.get("app_name", "?")
        title = st.get("window_title", "")[:60]
        text = st.get("extracted_text", "")[:200]
        entries.append(f"[{app}] {title}: {text}")

    combined = "\n".join(entries)
    if len(combined) > 3000:
        combined = combined[:3000] + "..."

    response = await call_llm(
        [{"role": "user", "content": combined}],
        tier="light",
        system=SCREEN_SUMMARY_SYSTEM,
        max_tokens=512,
    )
    return extract_text(response)


async def _gather_briefing_data(
    db: aiosqlite.Connection,
    briefing_type: str = "morning",
) -> dict[str, Any]:
    """Gather ALL data sources for briefing generation."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today_start = f"{today}T00:00:00"
    today_end = f"{today}T23:59:59"
    yesterday_start = f"{yesterday}T00:00:00"
    yesterday_end = f"{yesterday}T23:59:59"
    week_ago = (now - timedelta(days=7)).isoformat()

    # 1. Activity summary (today + yesterday for comparison)
    today_activity = await get_daily_summary(db, date=today)
    yesterday_activity = await get_daily_summary(db, date=yesterday)

    # 2. Calendar events — today + next 2 days
    upcoming_events = await crud.get_upcoming_events(
        db, since=today_start, until=(now + timedelta(days=2)).isoformat()
    )

    # 3. Unreplied emails
    unreplied_emails = await crud.get_unreplied_emails(db, limit=20)

    # 4. Promises — pending + overdue
    pending_promises = await crud.get_promises(db, status="pending")
    overdue_promises = await crud.get_promises(db, status="overdue")

    # 5. Recent transcripts
    recent_transcripts = await crud.get_transcripts(db, since=week_ago, limit=10)

    # 6. Location history (today)
    locations = await crud.get_locations(db, since=today_start, until=today_end, limit=20)

    # 7. Recent app usage details
    mobile_usage = await crud.get_app_usage(
        db,
        since=yesterday_start if briefing_type == "morning" else today_start,
        until=today_end,
        device="mobile",
        limit=50,
    )
    pc_usage = await crud.get_pc_activity(
        db,
        since=yesterday_start if briefing_type == "morning" else today_start,
        until=today_end,
        limit=50,
    )

    # 8. Screen text (summarized with Haiku to save tokens)
    screen_texts = await crud.get_screen_texts(
        db,
        since=yesterday_start if briefing_type == "morning" else today_start,
        until=today_end,
        limit=30,
    )
    screen_summary = ""
    if screen_texts:
        screen_summary = await _summarize_screen_texts(screen_texts)

    return {
        "type": briefing_type,
        "today": today,
        "yesterday": yesterday,
        "today_activity": today_activity,
        "yesterday_activity": yesterday_activity,
        "upcoming_events": upcoming_events,
        "unreplied_emails": unreplied_emails,
        "pending_promises": pending_promises,
        "overdue_promises": overdue_promises,
        "recent_transcripts": recent_transcripts,
        "locations": locations,
        "mobile_usage_detail": mobile_usage[:20],
        "pc_usage_detail": pc_usage[:20],
        "screen_summary": screen_summary,
    }


def _build_context_message(data: dict[str, Any]) -> str:
    """Build a structured text representation of all data for Claude."""
    parts = []

    # Calendar
    events = data.get("upcoming_events", [])
    if events:
        lines = []
        for e in events:
            time_str = e.get("start_time", "")[:16].replace("T", " ")
            lines.append(f"  - [{time_str}] {e['title']}" +
                        (f" @ {e['location']}" if e.get("location") else ""))
        parts.append("## 일정\n" + "\n".join(lines))
    else:
        parts.append("## 일정\n  예정된 일정 없음")

    # Unreplied emails
    emails = data.get("unreplied_emails", [])
    if emails:
        lines = [f"  - [{e.get('priority', 'normal')}] {e['subject']} (from: {e['sender']})"
                 for e in emails]
        parts.append(f"## 미답장 이메일 ({len(emails)}건)\n" + "\n".join(lines))

    # Promises
    pending = data.get("pending_promises", [])
    overdue = data.get("overdue_promises", [])
    if pending or overdue:
        lines = []
        for p in overdue:
            lines.append(f"  - [지연] {p['content']}" +
                        (f" (마감: {p['due_date']})" if p.get("due_date") else ""))
        for p in pending:
            lines.append(f"  - [대기] {p['content']}" +
                        (f" (마감: {p['due_date']})" if p.get("due_date") else ""))
        parts.append(f"## 약속 이행 현황 (지연: {len(overdue)}, 대기: {len(pending)})\n" + "\n".join(lines))

    # Activity summary
    ta = data.get("today_activity", {})
    ya = data.get("yesterday_activity", {})
    activity_lines = []

    if data["type"] == "morning":
        # Morning: show yesterday's summary, fallback to today if empty
        total = ya.get("total_active_s", 0)
        if total == 0:
            # Fallback to today's data if yesterday has none
            total = ta.get("total_active_s", 0)
            mob = ta.get("mobile", {}).get("total_s", 0)
            pc = ta.get("pc", {}).get("total_s", 0)
            activity_lines.append(f"  최근 활동: {format_duration(total)} (모바일: {format_duration(mob)}, PC: {format_duration(pc)})")
        else:
            mob = ya.get("mobile", {}).get("total_s", 0)
            pc = ya.get("pc", {}).get("total_s", 0)
            activity_lines.append(f"  어제 총 활동: {format_duration(total)} (모바일: {format_duration(mob)}, PC: {format_duration(pc)})")
    else:
        # Evening: show today's summary
        total = ta.get("total_active_s", 0)
        mob = ta.get("mobile", {}).get("total_s", 0)
        pc = ta.get("pc", {}).get("total_s", 0)
        y_total = ya.get("total_active_s", 0)
        activity_lines.append(f"  오늘 총 활동: {format_duration(total)} (모바일: {format_duration(mob)}, PC: {format_duration(pc)})")
        if y_total:
            diff = total - y_total
            direction = "증가" if diff > 0 else "감소"
            activity_lines.append(f"  어제 대비: {format_duration(abs(diff))} {direction}")

    # Top apps — fallback to today if yesterday is empty for morning
    if data["type"] == "morning":
        ref_activity = ya if ya.get("total_active_s", 0) > 0 else ta
    else:
        ref_activity = ta
    top_apps = ref_activity.get("top_apps", [])
    if top_apps:
        for app in top_apps[:5]:
            activity_lines.append(f"  - {app['name']} ({app['device']}): {format_duration(app['seconds'])}")

    parts.append("## 활동 요약\n" + "\n".join(activity_lines))

    # Transcripts
    transcripts = data.get("recent_transcripts", [])
    if transcripts:
        lines = []
        for tr in transcripts[:5]:
            summary = tr.get("summary") or tr["text"][:100]
            source_label = {"mic": "녹음", "call": "통화", "upload": "업로드"}.get(tr["source"], tr["source"])
            lines.append(f"  - [{source_label}] {summary}")
        parts.append("## 최근 녹음/통화\n" + "\n".join(lines))

    # Locations
    locations = data.get("locations", [])
    if locations:
        labels = set()
        for loc in locations:
            if loc.get("label"):
                labels.add(loc["label"])
        if labels:
            parts.append(f"## 위치 기록\n  방문 장소: {', '.join(labels)}")

    # Screen text summary (Haiku-summarized)
    screen_summary = data.get("screen_summary", "")
    if screen_summary:
        parts.append(f"## 화면 활동 요약\n{screen_summary}")

    return "\n\n".join(parts)


class BriefingAgent(BaseAgent):
    name = "briefing"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        return await self.generate_briefing(context)

    async def generate_briefing(
        self,
        context: dict[str, Any],
        briefing_type: str = "morning",
    ) -> str:
        db = context.get("db")
        if db is None:
            return "데이터베이스 연결이 필요합니다."

        # Gather ALL data sources
        data = await _gather_briefing_data(db, briefing_type)
        context_message = _build_context_message(data)

        system = MORNING_SYSTEM if briefing_type == "morning" else EVENING_SYSTEM

        messages = [
            {"role": "user", "content": f"오늘 날짜: {data['today']}\n\n{context_message}\n\n브리핑을 생성해 주세요."},
        ]

        response = await call_llm(messages, tier="medium", system=system)
        briefing_text = extract_text(response)

        # Save briefing to DB
        await crud.insert_briefing(
            db,
            type=briefing_type,
            content=briefing_text,
            locale=context.get("locale", "ko"),
        )

        return briefing_text
