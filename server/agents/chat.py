"""General chat agent — freeform conversation with context awareness.

KEY DESIGN: The chat agent automatically loads recent screen_texts
so it knows what the user has been doing. This is what makes it a
"secretary who knows everything" vs a generic chatbot.
"""

from __future__ import annotations

import logging
from typing import Any

from server.agents.base import BaseAgent, call_llm, extract_text
from server.database import crud

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 J.A.R.V.I.S, 사용자의 전담 AI 비서입니다.
사용자의 PC 화면, 이메일, 일정, 할 일을 모두 알고 있습니다.

아래에 사용자가 최근에 본 화면/사이트 정보가 있습니다.
이 데이터를 기반으로 사용자의 질문에 **구체적으로** 답변하세요.

중요 규칙:
- "날씨 어때?" → 화면 데이터에 날씨 정보가 있으면 그걸 기반으로 답변
- "주가 얼마야?" → 화면 데이터에 증권 정보가 있으면 그걸 기반으로 답변
- "아까 뭐 했어?" → 화면 데이터 목록을 보고 답변
- 화면 데이터에 답이 있으면 "확인해보세요"라고 하지 말고 직접 답변
- 한국어, 간결하게, 이모지 없음"""


class ChatAgent(BaseAgent):
    name = "chat"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        db = context.get("db")
        history = context.get("history", [])

        # ── Auto-inject recent screen context ──
        screen_context = ""
        if db:
            try:
                recent = await crud.get_screen_texts(db, limit=15)
                if recent:
                    lines = []
                    for st in recent:
                        app = st.get("app_name", "")
                        title = (st.get("window_title") or "")[:60]
                        text_preview = (st.get("extracted_text") or "")[:200]
                        ts = (st.get("timestamp") or "")[:16]
                        lines.append(f"[{ts}] {app}: {title}\n  {text_preview}")
                    screen_context = "\n".join(lines[:15])
            except Exception:
                logger.debug("Failed to load screen context for chat")

        messages = []
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})

        # Build user message with screen context
        user_msg = user_input
        if screen_context:
            user_msg = f"[최근 화면 데이터]\n{screen_context}\n\n[사용자 질문]\n{user_input}"

        messages.append({"role": "user", "content": user_msg})

        system = SYSTEM_PROMPT
        if context.get("user_summary"):
            system += f"\n\n현재 사용자 상태 요약:\n{context['user_summary']}"

        response = await call_llm(messages, tier="medium", system=system, purpose="chat")
        return extract_text(response)
