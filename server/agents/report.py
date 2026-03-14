"""Report agent - generates weekly/monthly activity reports.

Synthesizes:
- Trend data (activity changes week-over-week)
- Productivity scores (daily breakdown + average)
- Promise tracking (fulfillment rate)
- Top apps/programs
- Insights and recommendations
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from server.agents.base import BaseAgent, call_llm, extract_text
from server.analytics.activity_analyzer import format_duration
from server.analytics.promise_tracker import get_promise_summary
from server.analytics.productivity_score import calculate_daily_score
from server.analytics.trend_analyzer import weekly_trend
from server.database import crud

logger = logging.getLogger(__name__)

REPORT_SYSTEM = """당신은 J.A.R.V.I.S, 사용자의 주간 활동 리포트를 작성하는 AI 비서입니다.

## 리포트 구성
1. **주간 개요** - 총 활동 시간, 전주 대비 변화
2. **생산성 점수** - 일별 점수, 주간 평균, 트렌드
3. **활동 분석** - 모바일 vs PC 비율, 주요 앱/프로그램 Top 5
4. **약속 이행** - 이번 주 약속 이행률, 미이행 약속 리스트
5. **인사이트** - 데이터 기반 패턴 분석, 긍정적 톤의 제안

## 톤 가이드
- 긍정적이고 지지적인 톤 유지
- 판단하지 않음 - "SNS를 너무 많이 했다"가 아니라 "여유 시간이 많았다"
- 구체적 숫자와 비교 데이터 포함
- 실행 가능한 제안 1-2개
- 이모지 사용하지 않음
- 한국어로 작성"""


async def _gather_report_data(
    db: aiosqlite.Connection,
    report_type: str = "weekly",
) -> dict[str, Any]:
    """Gather all data for report generation."""
    trend = await weekly_trend(db)
    promise_summary = await get_promise_summary(db)

    # Daily scores for the week
    daily_scores = []
    for day in trend.get("daily_breakdown", []):
        score = await calculate_daily_score(db, date=day["date"])
        daily_scores.append({
            "date": day["date"],
            "score": score["score"],
            "grade": score["grade"],
            "insights": score["insights"],
        })

    return {
        "type": report_type,
        "trend": trend,
        "daily_scores": daily_scores,
        "promises": promise_summary,
    }


def _build_report_context(data: dict[str, Any]) -> str:
    """Build structured text for Claude."""
    parts = []
    trend = data.get("trend", {})
    comp = trend.get("comparison", {})

    # Overview
    active = comp.get("total_active", {})
    parts.append(f"## 주간 활동 개요")
    parts.append(f"  기간: {trend.get('period', 'N/A')}")
    parts.append(f"  총 활동 시간: {active.get('this_week_formatted', '0')}")
    parts.append(f"  전주 대비: {active.get('change_pct', 0):+.1f}%")
    mvp = comp.get("mobile_vs_pc", {})
    parts.append(f"  모바일: {mvp.get('mobile_pct', 0):.0f}% / PC: {mvp.get('pc_pct', 0):.0f}%")

    # Daily scores
    scores = data.get("daily_scores", [])
    if scores:
        lines = [f"  {s['date']}: {s['score']}점 ({s['grade']})" for s in scores]
        avg = comp.get("avg_score", {})
        parts.append(f"\n## 생산성 점수")
        parts.append("\n".join(lines))
        parts.append(f"  주간 평균: {avg.get('this_week', 0)}점 (전주: {avg.get('last_week', 0)}점, {avg.get('change', 0):+.1f})")

    # Top apps
    top = trend.get("top_apps", {})
    if top.get("pc"):
        lines = []
        for a in top["pc"][:5]:
            dur = format_duration(a.get("total_seconds") or 0)
            lines.append(f"  - {a.get('process_name', '?')}: {dur}")
        parts.append(f"\n## PC 주요 프로그램\n" + "\n".join(lines))
    if top.get("mobile"):
        lines = []
        for a in top["mobile"][:5]:
            dur = format_duration(a.get("total_seconds") or 0)
            lines.append(f"  - {a.get('app', '?')}: {dur}")
        parts.append(f"\n## 모바일 주요 앱\n" + "\n".join(lines))

    # Promises
    prom = data.get("promises", {})
    parts.append(f"\n## 약속 이행 현황")
    parts.append(f"  이행: {prom.get('done', 0)} / 지연: {prom.get('overdue', 0)} / 대기: {prom.get('pending', 0)}")
    parts.append(f"  이행률: {prom.get('completion_rate', 0) * 100:.0f}%")
    for item in prom.get("overdue_items", [])[:3]:
        parts.append(f"  - [지연] {item.get('content', '?')}")

    return "\n".join(parts)


class ReportAgent(BaseAgent):
    name = "report"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        return await self.generate_report(context)

    async def generate_report(
        self,
        context: dict[str, Any],
        report_type: str = "weekly",
    ) -> str:
        db = context.get("db")
        if db is None:
            return "DB connection required."

        data = await _gather_report_data(db, report_type)
        report_context = _build_report_context(data)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        messages = [
            {"role": "user", "content": f"오늘 날짜: {today}\n\n{report_context}\n\n주간 리포트를 작성해 주세요."},
        ]

        response = await call_llm(messages, tier="medium", system=REPORT_SYSTEM)
        report_text = extract_text(response)

        # Save as briefing type=weekly
        await crud.insert_briefing(
            db,
            type="weekly",
            content=report_text,
            locale=context.get("locale", "ko"),
        )

        return report_text
