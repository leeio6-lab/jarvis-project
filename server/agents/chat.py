"""General chat agent — freeform conversation with Claude Sonnet."""

from __future__ import annotations

import logging
from typing import Any

from server.agents.base import BaseAgent, call_llm, extract_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 J.A.R.V.I.S, 사용자의 개인 AI 비서입니다.
한국어로 자연스럽게 대화하며, 사용자의 질문에 정확하고 간결하게 답변합니다.
사용자의 일정, 이메일, 활동 데이터에 접근할 수 있는 AI 비서로서 맥락을 이해하고 도움을 제공합니다.
답변은 간결하되 필요한 정보는 빠뜨리지 않습니다."""


class ChatAgent(BaseAgent):
    name = "chat"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        history = context.get("history", [])

        messages = []
        for h in history[-10:]:  # keep last 10 turns
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_input})

        system = SYSTEM_PROMPT
        if context.get("user_summary"):
            system += f"\n\n현재 사용자 상태 요약:\n{context['user_summary']}"

        response = await call_llm(messages, tier="medium", system=system)
        return extract_text(response)
