"""Task agent — TODO CRUD via natural language or direct API."""

from __future__ import annotations

import json
import logging
from typing import Any

from server.agents.base import BaseAgent, call_llm, extract_text, extract_tool_calls
from server.database import crud

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 J.A.R.V.I.S의 할 일 관리 에이전트입니다.
사용자의 요청을 분석하여 적절한 도구를 호출하세요.

할 일 관리 규칙:
- 사용자가 할 일을 추가하면 create_task 도구 사용
- 사용자가 할 일 목록을 요청하면 list_tasks 도구 사용
- 사용자가 할 일을 완료/수정하면 update_task 도구 사용
- 사용자가 할 일을 삭제하면 delete_task 도구 사용
- 한국어로 응답"""

TASK_TOOLS = [
    {
        "name": "create_task",
        "description": "새 할 일을 생성합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "할 일 제목"},
                "description": {"type": "string", "description": "상세 설명"},
                "due_date": {"type": "string", "description": "마감일 (YYYY-MM-DD)"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "할 일 목록을 조회합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
            },
        },
    },
    {
        "name": "update_task",
        "description": "할 일을 수정합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "할 일 ID"},
                "title": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                "due_date": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "할 일을 삭제합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "할 일 ID"},
            },
            "required": ["task_id"],
        },
    },
]


class TaskAgent(BaseAgent):
    name = "task"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        db = context.get("db")
        if db is None:
            return "데이터베이스 연결이 필요합니다."

        messages = [{"role": "user", "content": user_input}]
        response = await call_llm(messages, tier="medium", system=SYSTEM_PROMPT, tools=TASK_TOOLS)

        tool_calls = extract_tool_calls(response)
        if not tool_calls:
            return extract_text(response)

        # Execute tool calls and collect results
        tool_results = []
        for tc in tool_calls:
            result = await self._execute_tool(db, tc["name"], tc["input"])
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Send tool results back to Claude for final response
        messages.append({"role": "assistant", "content": response["content"]})
        messages.append({"role": "user", "content": tool_results})
        final = await call_llm(messages, tier="medium", system=SYSTEM_PROMPT)
        return extract_text(final)

    async def _execute_tool(self, db, tool_name: str, tool_input: dict) -> dict:
        if tool_name == "create_task":
            task_id = await crud.insert_task(
                db,
                title=tool_input["title"],
                description=tool_input.get("description"),
                due_date=tool_input.get("due_date"),
                priority=tool_input.get("priority", "normal"),
            )
            return {"success": True, "task_id": task_id, "message": "할 일이 생성되었습니다"}

        elif tool_name == "list_tasks":
            tasks = await crud.get_tasks(db, status=tool_input.get("status"))
            return {"tasks": tasks, "count": len(tasks)}

        elif tool_name == "update_task":
            task_id = tool_input.pop("task_id")
            ok = await crud.update_task(db, task_id, **tool_input)
            return {"success": ok, "message": "할 일이 수정되었습니다" if ok else "할 일을 찾을 수 없습니다"}

        elif tool_name == "delete_task":
            ok = await crud.delete_task(db, tool_input["task_id"])
            return {"success": ok, "message": "할 일이 삭제되었습니다" if ok else "할 일을 찾을 수 없습니다"}

        return {"error": f"Unknown tool: {tool_name}"}
