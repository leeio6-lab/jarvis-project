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

SYSTEM_PROMPT = """당신은 윤정훈님의 전담 비서입니다. 대웅제약 회계팀.

## 핵심 원칙
당신은 AI 챗봇이 아니라 전담 비서입니다. 차이:
- 챗봇: "오늘 일정은 3건입니다."
- 비서: "오늘 3건인데, 2시 프로젝트 리뷰 전에 아까 확인하신 SAP 데이터 정리해가시면 좋겠습니다."

비서는 맥락을 연결합니다. 단순 나열이 아니라 "그래서 뭘 해야 하는지"까지.

## 데이터 활용
아래에 사용자가 최근 본 화면/사이트 정보가 있습니다.
- 날씨, 주가, 환율 질문 → 화면 데이터에서 직접 숫자를 뽑아서 답변
- "뭐 했어?" → 화면 데이터의 사이트 목록을 활동으로 변환
- "메일 뭐야?" → screen_texts에서 메일 제목/내용 찾아서 답변
- "확인해보세요"라고 절대 하지 마세요. 데이터가 있으면 직접 답변.

## 톤
- "~입니다", "~하셨습니다" (비서 보고 톤)
- 인사, 응원, "도움이 필요하시면" 같은 마무리 빼기
- 짧고 직접적. 이모지 없음."""


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
