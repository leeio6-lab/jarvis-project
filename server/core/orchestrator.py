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
사용자의 의도를 파악하여 적절한 도구를 호출하세요.

가능한 작업:
- 일반 대화 → route_to_agent(agent="chat")
- 브리핑 요청 ("오늘 브리핑", "요약해줘") → route_to_agent(agent="briefing")
- 할 일 관리 ("할 일 추가", "TODO") → route_to_agent(agent="task")
- 활동 조회 ("오늘 뭐 했지", "앱 사용 시간") → get_activity_summary
- 이메일 확인 ("안 읽은 메일") → get_unreplied_emails
- 일정 확인 ("오늘 일정") → get_upcoming_events
- 약속 확인 ("약속 현황") → get_promises

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
        "description": "오늘 또는 특정 날짜의 모바일+PC 활동 요약을 조회합니다",
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
        "name": "get_promises",
        "description": "약속 이행 현황을 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "done", "overdue"]},
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
        return extract_text(response)

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
    return extract_text(final)


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

    return {"error": f"Unknown tool: {tool_name}"}
