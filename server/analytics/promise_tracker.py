"""Extracts promises/commitments from transcript text and tracks fulfillment.

THIS IS THE PHASE 3 KEY DIFFERENTIATOR.
No existing product does this: "You said you'd finish the report by Friday
in the Tuesday meeting, but you haven't done it yet."

Pipeline:
1. Transcript text comes in (from STT)
2. Claude Haiku extracts promises: {content, assignee, due_date}
3. Promises are saved to DB
4. Proactive agent (Phase 2) tracks fulfillment and alerts on overdue
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from server.agents.base import call_llm, extract_text
from server.database import crud

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM = """당신은 회의/통화 녹음 전사 텍스트에서 약속(commitment)을 추출하는 AI입니다.

약속이란: 누군가가 특정 행동을 하겠다고 말한 것.
예시:
- "금요일까지 보고서 수정해서 보내드리겠습니다" -> 약속
- "다음 주 월요일에 미팅하죠" -> 약속
- "그 건은 제가 확인해보겠습니다" -> 약속
- "날씨가 좋네요" -> 약속 아님

각 약속에 대해 다음 JSON 배열을 반환하세요:
[
  {
    "content": "약속 내용 (한 문장으로 요약)",
    "assignee": "누가 (이름/직함, 알 수 없으면 null)",
    "due_date": "마감일 (YYYY-MM-DD, 알 수 없으면 null)"
  }
]

규칙:
- 약속이 없으면 빈 배열 [] 반환
- "다음 주 월요일" 같은 상대 날짜는 today 기준으로 절대 날짜로 변환
- 확실하지 않은 것은 포함하지 않음
- JSON만 반환, 다른 텍스트 없이"""


async def extract_promises(
    text: str,
    *,
    transcript_id: int | None = None,
    today: str | None = None,
) -> list[dict[str, Any]]:
    """Extract promises from transcript text using Claude Haiku.

    Returns list of extracted promise dicts.
    """
    if not text or len(text.strip()) < 10:
        return []

    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    messages = [
        {"role": "user", "content": f"오늘 날짜: {today}\n\n전사 텍스트:\n{text}"},
    ]

    response = await call_llm(
        messages,
        tier="light",
        system=EXTRACTION_SYSTEM,
        max_tokens=1024,
    )

    raw = extract_text(response)

    # Parse JSON from response
    promises = _parse_promises(raw)
    if transcript_id is not None:
        for p in promises:
            p["transcript_id"] = transcript_id

    logger.info("Extracted %d promises from transcript (id=%s)", len(promises), transcript_id)
    return promises


def _parse_promises(raw: str) -> list[dict[str, Any]]:
    """Parse Claude's response into a list of promise dicts."""
    raw = raw.strip()

    # Handle mock responses (no API key)
    if raw.startswith("[MOCK]"):
        return _mock_extract(raw)

    # Try to find JSON array in the response
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Try parsing the whole thing
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    logger.warning("Could not parse promises from Claude response: %s", raw[:200])
    return []


def _mock_extract(raw: str) -> list[dict[str, Any]]:
    """Extract promises from text using simple keyword matching (mock mode)."""
    # Simple heuristic for when API is not available
    keywords = ["까지", "하겠", "할게", "드리겠", "보내겠", "제출", "완료", "마감"]
    text = raw.lower()
    if any(kw in text for kw in keywords):
        return [{
            "content": "[MOCK] 약속이 감지되었습니다 (API 키 설정 시 정확한 추출)",
            "assignee": None,
            "due_date": None,
        }]
    return []


async def process_transcript_promises(
    db: aiosqlite.Connection,
    transcript_id: int,
    text: str,
) -> list[dict[str, Any]]:
    """Full pipeline: extract promises from transcript and save to DB.

    Called after STT transcription completes.
    """
    promises = await extract_promises(text, transcript_id=transcript_id)

    saved = []
    for p in promises:
        pid = await crud.insert_promise(
            db,
            transcript_id=transcript_id,
            content=p.get("content", ""),
            assignee=p.get("assignee"),
            due_date=p.get("due_date"),
        )
        saved.append({**p, "id": pid})

    if saved:
        logger.info("Saved %d promises from transcript %d", len(saved), transcript_id)
    return saved


async def get_promise_summary(db: aiosqlite.Connection) -> dict[str, Any]:
    """Get a summary of all promise statuses."""
    pending = await crud.get_promises(db, status="pending")
    done = await crud.get_promises(db, status="done")
    overdue = await crud.get_promises(db, status="overdue")

    return {
        "total": len(pending) + len(done) + len(overdue),
        "pending": len(pending),
        "done": len(done),
        "overdue": len(overdue),
        "pending_items": pending[:10],
        "overdue_items": overdue[:10],
        "completion_rate": len(done) / max(len(done) + len(overdue), 1),
    }
