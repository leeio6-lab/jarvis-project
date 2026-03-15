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

ORCHESTRATOR_SYSTEM = """당신은 J.A.R.V.I.S 오케스트레이터입니다.
사용자의 의도를 파악하여 **반드시** 적절한 도구를 호출하세요.

중요: 절대로 도구 없이 직접 답변하지 마세요. 어떤 질문이든 반드시 아래 도구 중 하나를 호출하세요.

라우팅 규칙 (우선순위 순서):
1. 화면 데이터 검색 → get_screen_texts (query 파라미터에 키워드)
   - 사용자가 최근에 본 것: "날씨 어때?", "주가 얼마야?", "환율?", "뉴스 뭐 나와?"
   - 과거 참조: "아까", "방금", "전에", "얼마였어"
   - 특정 사이트/앱 질문: "웍스에서 뭐 봤어", "SAP에서 뭐 했어"
   - 핵심: 사용자가 뭔가를 "본 적이 있을 수 있는" 질문이면 무조건 get_screen_texts
2. 활동 조회 → get_activity_summary: "오늘 뭐 했어", "업무 외 활동", "비업무"
3. 미답장 메일 → get_unreplied_emails: "메일", "미답장", "급한 거", "중요한 일"
4. 일정 조회 → get_upcoming_events: "오늘 일정", "내일 회의"
5. 일정 등록 → create_calendar_event: "회의 등록", "일정 추가"
6. 할 일 → route_to_agent(agent="task"): "할 일 추가/보여줘/삭제"
7. 브리핑 → route_to_agent(agent="briefing"): "브리핑", "요약"
8. 생산성 → get_productivity_score: "생산성 점수"
9. 약속 → get_promises: "약속 현황"
10. 전문 지식/일반 대화 → route_to_agent(agent="chat"): 위에 해당 안 되는 것

핵심 원칙: 사용자가 PC에서 무언가를 보면서 질문하는 상황을 항상 가정하세요.
"날씨", "주가", "환율", "뉴스" 같은 키워드가 있으면 get_screen_texts(query=키워드)를 먼저 호출하세요.
도구를 호출한 뒤 결과를 바탕으로 사용자에게 자연스럽게 답변하세요.
한국어로 응답합니다."""

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


async def handle_message(
    user_input: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Main entry point: route user message through the orchestrator."""
    context = context or {}
    db = context.get("db") or get_db()
    context["db"] = db

    messages = []
    history = context.get("history", [])
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_input})

    response = await call_llm(
        messages, tier="medium", system=ORCHESTRATOR_SYSTEM, tools=ORCHESTRATOR_TOOLS
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
