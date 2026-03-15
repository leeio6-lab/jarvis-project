"""Agent orchestrator — routes user intent to the right agent via Claude tool-use."""

from __future__ import annotations

import json
import logging
from typing import Any

from server.agents.base import call_llm, extract_text, extract_tool_calls
from server.agents.registry import get_agent, list_agents
from server.database import crud
from server.database.db import get_db

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM = """당신은 윤정훈님의 전담 비서(오케스트레이터)입니다.
사용자 질문을 분석해서 **필요한 도구를 전부** 호출하세요. 여러 개 동시 호출 가능.

## 도구 선택 가이드
- "내일 뭐 해야 해?" → get_upcoming_events + get_unreplied_emails + route_to_agent(task) 3개 동시
- "오늘 뭐했어?" → get_activity_summary
- "날씨 어때?", "주가?", "아까 본 거" → get_screen_texts(query=키워드)
- "미답장 메일" → get_unreplied_emails
- "일정" → get_upcoming_events
- "회의 등록", "일정 추가" → create_calendar_event
- "할 일 추가/완료/삭제" → route_to_agent(agent="task")
- "브리핑" → route_to_agent(agent="briefing")
- "생산성" → get_productivity_score
- "XX 메일 뭐야?" → get_screen_texts(query=XX)
- 전문 지식, 일반 대화 → route_to_agent(agent="chat")

## 핵심 원칙
1. 복합 질문이면 도구 여러 개 호출. 하나만 호출하지 마.
2. "아까", "방금", "전에" 등 과거 참조 → get_screen_texts
3. 도구 결과를 종합해서 비서처럼 보고. "~입니다" 톤.
4. 인사/응원 빼고 본론만. 이모지 없음.
5. 도구 없이 직접 답변하지 마. 반드시 도구 호출.
한국어로 응답."""

ORCHESTRATOR_TOOLS = [
    {
        "name": "route_to_agent",
        "description": "특정 에이전트로 사용자 요청을 라우팅합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["chat", "briefing", "task"],
                    "description": "라우팅할 에이전트",
                },
                "message": {
                    "type": "string",
                    "description": "에이전트에 전달할 메시지 (원본 유지)",
                },
            },
            "required": ["agent", "message"],
        },
    },
    {
        "name": "get_activity_summary",
        "description": "오늘 또는 특정 날짜의 모바일+PC 활동과 방문 사이트 요약을 조회합니다. '오늘 뭐했어?', '어제 뭐했어?' 등의 질문에 사용합니다. 앱 사용시간과 화면에서 캡처된 방문 사이트 목록을 모두 포함합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "조회할 날짜 (YYYY-MM-DD). 미지정시 오늘"},
            },
        },
    },
    {
        "name": "get_unreplied_emails",
        "description": "미답장 이메일 목록을 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 개수"},
            },
        },
    },
    {
        "name": "get_upcoming_events",
        "description": "다가오는 일정 목록을 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "며칠 후까지 조회할지"},
            },
        },
    },
    {
        "name": "create_calendar_event",
        "description": "캘린더에 일정을 등록합니다. '회의 등록', '일정 추가' 등의 요청에 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "일정 제목"},
                "date": {"type": "string", "description": "날짜 (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "시간 (HH:MM)"},
                "duration_minutes": {"type": "integer", "description": "소요 시간(분)"},
            },
            "required": ["title", "date", "time"],
        },
    },
    {
        "name": "get_promises",
        "description": "약속 이행 현황을 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "done", "overdue"]},
            },
        },
    },
    {
        "name": "get_screen_texts",
        "description": "PC 화면에서 캡처된 텍스트를 검색합니다. '네이버 웍스에서 뭐 봤어?', '임상민 메일', '어제 뭐 했어?', '화면에서 본 거 알려줘' 등의 질문에 사용합니다. 키워드로 필터링하려면 query에 검색어를 넣으세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 키워드 (선택)"},
                "since": {"type": "string", "description": "시작 날짜/시간 (ISO format, 선택)"},
                "limit": {"type": "integer", "description": "최대 결과 수 (기본 30)"},
            },
        },
    },
    {
        "name": "get_productivity_score",
        "description": "생산성 점수를 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "조회할 날짜 (YYYY-MM-DD). 미지정시 오늘"},
            },
        },
    },
]


# ── Fast-path patterns: skip orchestrator LLM, go directly to data+synthesis ──

# Fast-path: 단순 1:1 조회만. 복합 질문은 오케스트레이터 LLM이 판단.
_FAST_PATTERNS = {
    # 확실한 단순 조회만 여기에. 애매한 건 LLM한테.
    "할 일 보여": "list_tasks",
    "할일 보여": "list_tasks",
    "할 일 목록": "list_tasks",
    "미답장 메일": "unreplied_emails",
    "답장 안 한": "unreplied_emails",
}


async def _try_fast_path(user_input: str, context: dict) -> str | None:
    """Fast-path: directly fetch data and synthesize response in 1 LLM call."""
    db = context["db"]
    lower = user_input.lower().replace(" ", "")

    matched_action = None
    for pattern, action in _FAST_PATTERNS.items():
        if pattern.replace(" ", "") in lower:
            matched_action = action
            break

    if not matched_action:
        return None

    # Fetch data directly from DB
    data_str = ""
    if matched_action == "list_tasks":
        tasks = await crud.get_tasks(db, status="pending", limit=30)
        if not tasks:
            return "현재 등록된 할 일이 없습니다."
        # Sort by due_date (soonest first), nulls last
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        def sort_key(t):
            d = t.get("due_date", "9999-12-31")
            return d if d else "9999-12-31"
        tasks.sort(key=sort_key)

        lines = []
        for t in tasks:
            due = t.get("due_date", "")
            title = t.get("title", "?")
            urgent = ""
            if due and due <= now:
                urgent = " [오늘 마감!]"
            elif due:
                try:
                    days_left = (datetime.fromisoformat(due) - datetime.fromisoformat(now)).days
                    if days_left == 1:
                        urgent = " [내일 마감]"
                    elif days_left <= 3:
                        urgent = f" [{days_left}일 남음]"
                except (ValueError, TypeError):
                    pass
            p = " [우선]" if t.get("priority") == "high" else ""
            line = f"- {title} (마감: {due}){urgent}{p}" if due else f"- {title}{p}"
            lines.append(line)
        data_str = f"할 일 {len(tasks)}건 (마감순):\n" + "\n".join(lines)
        data_str += "\n\n비서 지시: 마감이 임박한 것을 강조하고, 어떻게 처리하면 좋을지 한마디씩 붙여주세요."

    elif matched_action == "unreplied_emails":
        emails = await crud.get_unreplied_emails(db, limit=20)
        if not emails:
            return "현재 미답장 메일이 없습니다."
        # Calculate hours since received
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        lines = []
        for e in emails[:10]:
            subject = e.get("subject", "?")
            sender = e.get("sender", "unknown")
            priority = e.get("priority", "normal")
            received = e.get("received_at", "")
            # Calculate elapsed time
            hours_str = ""
            try:
                recv_dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
                hours = (now - recv_dt).total_seconds() / 3600
                if hours >= 48:
                    hours_str = f" — {int(hours)}시간 경과, 긴급 회신 필요"
                elif hours >= 24:
                    hours_str = f" — {int(hours)}시간 경과"
                else:
                    hours_str = f" — {int(hours)}시간 전 수신"
            except (ValueError, TypeError):
                pass
            urgency = "[최우선]" if priority == "high" and sender != "unknown" else "[긴급]" if priority == "high" else ""
            lines.append(f"- {subject} {urgency} (from {sender}){hours_str}")
        data_str = f"미답장 메일 {len(emails)}건:\n" + "\n".join(lines)
        if len(emails) > 10:
            data_str += f"\n외 {len(emails) - 10}건"
        data_str += "\n\n비서 지시: 각 메일에 대해 짧은 답장 초안(1~2줄)을 제안해주세요. '확인했습니다, 검토 후 회신드리겠습니다' 같은 수준."

    if not data_str:
        return None

    # Single LLM call to synthesize natural response
    messages = [
        {"role": "user", "content": f"사용자 질문: {user_input}\n\n데이터:\n{data_str}"},
    ]
    system = (
        "당신은 윤정훈님의 전담 비서입니다. 월 300만원 받는 비서처럼 보고하세요. "
        "데이터를 있는 그대로 활용. 없는 건 추측하지 마세요. "
        "[비업무 사이트]에 나온 것은 반드시 비업무로 보고. "
        "total_active_s가 0이어도 [업무/비업무 사이트] 데이터가 있으면 그것이 활동입니다. "
        "톤: 비서가 보고하듯. 인사/응원 빼고 본론만. 이모지 없음. "
        "미답장 메일을 보고할 때는 각 메일에 짧은 답장 초안(1줄)을 함께 제안하세요."
    )
    response = await call_llm(messages, tier="medium", system=system, purpose="fast_path")
    return extract_text(response)


async def handle_message(
    user_input: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Main entry point: route user message through the orchestrator."""
    context = context or {}
    db = context.get("db") or get_db()
    context["db"] = db

    # ── Fast-path: skip orchestrator LLM call for obvious patterns ──
    fast = await _try_fast_path(user_input, context)
    if fast is not None:
        return fast

    messages = []
    history = context.get("history", [])
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_input})

    response = await call_llm(
        messages, tier="medium", system=ORCHESTRATOR_SYSTEM, tools=ORCHESTRATOR_TOOLS,
        purpose="orchestrator",
    )

    tool_calls = extract_tool_calls(response)
    if not tool_calls:
        # Fallback: LLM sometimes generates tool calls as plain text
        text = extract_text(response)
        result = await _try_text_fallback(text, user_input, context, messages)
        return result if result else text

    # Execute tool calls
    tool_results = []
    for tc in tool_calls:
        result = await _execute_tool(tc["name"], tc["input"], context)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tc["id"],
            "content": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
        })

    # Send results back to Claude for final natural-language response
    messages.append({"role": "assistant", "content": response["content"]})
    messages.append({"role": "user", "content": tool_results})
    final = await call_llm(messages, tier="medium", system=ORCHESTRATOR_SYSTEM)
    final_text = extract_text(final)

    # If the final response still contains raw tool/JSON text, clean it up
    if "route_to_agent" in final_text or final_text.strip().startswith("{"):
        # The tool result IS the response — return it directly
        for tr in tool_results:
            content = tr.get("content", "")
            if content and len(content) > 5 and "route_to_agent" not in content:
                # Try to extract clean text from JSON agent response
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "content" in parsed:
                        return parsed["content"]
                except (json.JSONDecodeError, TypeError):
                    pass
                return content
    # Also clean up if final_text itself is JSON
    if final_text.strip().startswith("{"):
        try:
            parsed = json.loads(final_text)
            if isinstance(parsed, dict) and "content" in parsed:
                return parsed["content"]
        except (json.JSONDecodeError, TypeError):
            pass
    return final_text


async def _try_text_fallback(
    text: str,
    user_input: str,
    context: dict[str, Any],
    messages: list,
) -> str | None:
    """Handle cases where LLM outputs tool calls as plain text instead of tool_use."""
    import re

    # Check for route_to_agent pattern (various quote styles)
    if "route_to_agent" in text:
        match = re.search(r'agent["\s:=]+(\w+)', text)
        logger.info("Fallback: route_to_agent detected, match=%s, text=%s", match, text[:80])
        if match:
            agent_type = match.group(1)
            agent = get_agent(agent_type)
            if agent:
                result = await agent.run(user_input, context)
                # If the agent returns JSON-like text, extract the message
                if isinstance(result, str) and result.startswith("{"):
                    try:
                        parsed = json.loads(result)
                        if "content" in parsed:
                            return parsed["content"]
                        if "parameters" in parsed and "content" in parsed["parameters"]:
                            return parsed["parameters"]["content"]
                    except (json.JSONDecodeError, KeyError):
                        pass
                return result
        return None

    # Check for other tool patterns in text — execute and synthesize response
    tool_names = [
        "get_screen_texts", "get_activity_summary", "get_productivity_score",
        "get_unreplied_emails", "get_upcoming_events", "get_promises",
        "create_calendar_event",
    ]
    for tool_name in tool_names:
        if tool_name in text:
            result = await _execute_tool(tool_name, {}, context)
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            # Build a clean follow-up asking LLM to summarize
            synthesis_messages = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": f"{tool_name} 결과를 조회했습니다."},
                {
                    "role": "user",
                    "content": f"아래는 조회 결과입니다. 이 데이터를 바탕으로 사용자의 원래 질문 '{user_input}'에 자연스러운 한국어로 답변하세요. 도구명이나 JSON을 사용자에게 보여주지 마세요.\n\n{content[:3000]}",
                },
            ]
            final = await call_llm(synthesis_messages, tier="medium", system=ORCHESTRATOR_SYSTEM, purpose="fallback_synthesis")
            final_text = extract_text(final)
            # Safety: if still contains tool names, strip them
            for tn in tool_names:
                if final_text.strip() == tn:
                    return f"데이터를 조회했습니다. 현재 관련 정보가 제한적입니다."
            return final_text

    return None


async def _execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    context: dict[str, Any],
) -> str | dict:
    db = context["db"]

    if tool_name == "route_to_agent":
        agent_type = tool_input["agent"]
        agent = get_agent(agent_type)
        if agent is None:
            return f"에이전트 '{agent_type}'을(를) 찾을 수 없습니다. 사용 가능: {list_agents()}"
        result = await agent.run(tool_input.get("message", ""), context)
        return result

    elif tool_name == "get_activity_summary":
        from server.analytics.activity_analyzer import get_daily_summary
        summary = await get_daily_summary(db, date=tool_input.get("date"))
        return summary

    elif tool_name == "get_unreplied_emails":
        emails = await crud.get_unreplied_emails(db, limit=tool_input.get("limit", 20))
        return {"emails": emails, "count": len(emails)}

    elif tool_name == "get_upcoming_events":
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        days = tool_input.get("days", 7)
        events = await crud.get_upcoming_events(
            db, since=now.isoformat(), until=(now + timedelta(days=days)).isoformat()
        )
        return {"events": events, "count": len(events)}

    elif tool_name == "get_promises":
        promises = await crud.get_promises(db, status=tool_input.get("status"))
        return {"promises": promises, "count": len(promises)}

    elif tool_name == "get_screen_texts":
        query = tool_input.get("query")
        since = tool_input.get("since")
        limit = tool_input.get("limit", 50)
        # Always fetch recent data (ignore since if it would return 0 results)
        texts = await crud.get_screen_texts(db, since=since, limit=limit)
        if not texts and since:
            # Fallback: fetch without date filter
            texts = await crud.get_screen_texts(db, limit=limit)
        if query:
            q_lower = query.lower()
            filtered = [
                t for t in texts
                if q_lower in (t.get("extracted_text") or "").lower()
                or q_lower in (t.get("window_title") or "").lower()
                or q_lower in (t.get("app_name") or "").lower()
            ]
            if filtered:
                texts = filtered
            # If no keyword match, return all texts (let LLM interpret)
        # Compact: only send essential fields to reduce token usage
        compact = []
        for t in texts[:20]:
            compact.append({
                "app": t.get("app_name", ""),
                "title": (t.get("window_title") or "")[:60],
                "text": (t.get("extracted_text") or "")[:300],
                "time": (t.get("timestamp") or "")[:16],
            })
        return {"screen_texts": compact, "count": len(compact)}

    elif tool_name == "create_calendar_event":
        from server.core.auth import get_valid_google_token
        from server.crawlers.calendar_crawler import create_calendar_event
        title = tool_input.get("title", "새 일정")
        date = tool_input.get("date", "")
        time_str = tool_input.get("time", "")
        duration = tool_input.get("duration_minutes", 60)
        google_token = await get_valid_google_token(db)
        result = await create_calendar_event(
            db, google_token,
            title=title, date=date, time=time_str,
            duration_minutes=duration,
        )
        return result

    elif tool_name == "get_productivity_score":
        from server.analytics.productivity_score import calculate_daily_score
        score = await calculate_daily_score(db, date=tool_input.get("date"))
        return score

    return {"error": f"Unknown tool: {tool_name}"}
