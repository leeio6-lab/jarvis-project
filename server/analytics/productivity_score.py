"""Daily productivity score based on crawled activity data.

Scoring philosophy: NEVER judge the user. Frame everything positively.

App classification: NO hardcoded lists. Instead:
1. Check DB cache (app_categories table)
2. If unknown app → ask LLM (light tier) to classify → cache result
3. User can override any classification

Score components (0-100):
1. Focus ratio (40%) - work apps vs total active time
2. Deep work blocks (30%) - sustained 25min+ focus sessions
3. Task completion (20%) - tasks done today
4. Promise fulfillment (10%) - promises met
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.database import crud

logger = logging.getLogger(__name__)

DEEP_WORK_MIN_SECONDS = 25 * 60  # 25 minutes (Pomodoro)

# Seed data — only the absolutely obvious ones. Everything else goes to AI.
_SEED_CATEGORIES = {
    # Office / productivity
    "excel.exe": ("work", "spreadsheet"),
    "winword.exe": ("work", "document"),
    "powerpnt.exe": ("work", "presentation"),
    "onenote.exe": ("work", "notes"),
    # Terminal
    "cmd.exe": ("work", "terminal"),
    "powershell.exe": ("work", "terminal"),
    "windowsterminal.exe": ("work", "terminal"),
    # Obvious leisure
    "spotify.exe": ("leisure", "music"),
    "discord.exe": ("leisure", "gaming chat"),
}

# In-memory cache to avoid DB hits every call
_cache: dict[str, str] = {}  # app_name -> category
_cache_loaded = False


async def _ensure_seed(db: aiosqlite.Connection) -> None:
    """Insert seed categories if they don't exist yet."""
    for app, (cat, sub) in _SEED_CATEGORIES.items():
        existing = await crud.get_app_category(db, app)
        if not existing:
            await crud.upsert_app_category(
                db, app_name=app, category=cat,
                sub_category=sub, classified_by="seed",
            )


async def _load_cache(db: aiosqlite.Connection) -> None:
    """Load all app categories into memory cache."""
    global _cache, _cache_loaded
    all_cats = await crud.get_all_app_categories(db)
    _cache = {name: info["category"] for name, info in all_cats.items()}
    _cache_loaded = True


async def _classify_with_llm(app_name: str) -> tuple[str, str]:
    """Ask LLM to classify an unknown app. Returns (category, sub_category)."""
    from server.agents.base import call_llm, extract_text

    prompt = (
        f'Classify this application: "{app_name}"\n'
        f'Reply with exactly one JSON object: {{"category": "work"|"leisure"|"neutral", "sub": "short description"}}\n'
        f'Examples:\n'
        f'  "cursor.exe" -> {{"category": "work", "sub": "IDE"}}\n'
        f'  "instagram.exe" -> {{"category": "leisure", "sub": "SNS"}}\n'
        f'  "explorer.exe" -> {{"category": "neutral", "sub": "file manager"}}\n'
        f'  "saplogon.exe" -> {{"category": "work", "sub": "ERP"}}\n'
        f'  "kakaotalk.exe" -> {{"category": "neutral", "sub": "messenger"}}\n'
        f'JSON only, no other text.'
    )

    try:
        response = await call_llm(
            [{"role": "user", "content": prompt}],
            tier="light",
            max_tokens=100,
        )
        raw = extract_text(response).strip()

        # Handle mock response
        if raw.startswith("[MOCK]"):
            return "neutral", "unknown"

        # Parse JSON
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start:end + 1])
            cat = data.get("category", "neutral")
            sub = data.get("sub", "")
            if cat in ("work", "leisure", "neutral"):
                return cat, sub
    except Exception:
        logger.debug("LLM classification failed for %s, defaulting to neutral", app_name)

    return "neutral", "unknown"


async def classify_app(
    db: aiosqlite.Connection,
    app_name: str,
) -> str:
    """Classify an app as work/leisure/neutral. Uses cache → DB → LLM chain."""
    if not app_name:
        return "neutral"

    key = app_name.lower()

    # 1. Memory cache
    if not _cache_loaded:
        await _ensure_seed(db)
        await _load_cache(db)

    if key in _cache:
        return _cache[key]

    # 2. DB lookup (in case another process wrote it)
    existing = await crud.get_app_category(db, key)
    if existing:
        _cache[key] = existing["category"]
        return existing["category"]

    # 3. LLM classification
    category, sub = await _classify_with_llm(app_name)
    await crud.upsert_app_category(
        db, app_name=key, category=category,
        sub_category=sub, classified_by="auto",
    )
    _cache[key] = category
    logger.info("Auto-classified app: %s -> %s (%s)", app_name, category, sub)
    return category


async def calculate_daily_score(
    db: aiosqlite.Connection,
    date: str | None = None,
) -> dict[str, Any]:
    """Calculate the daily productivity score."""
    if date:
        since = f"{date}T00:00:00"
        until = f"{date}T23:59:59"
    else:
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        since = f"{date}T00:00:00"
        until = f"{date}T23:59:59"

    pc_records = await crud.get_pc_activity(db, since=since, until=until, limit=500)
    mobile_records = await crud.get_app_usage(db, since=since, until=until, limit=500)
    all_tasks = await crud.get_tasks(db, status="done", limit=100)
    tasks_today = [t for t in all_tasks if t.get("updated_at", "").startswith(date)]
    done_promises = await crud.get_promises(db, status="done")
    overdue_promises = await crud.get_promises(db, status="overdue")

    # === Component 1: Focus Ratio (40%) ===
    work_seconds = 0
    leisure_seconds = 0
    total_seconds = 0

    for r in pc_records:
        dur = r.get("duration_s") or 0
        if r.get("idle"):
            continue
        total_seconds += dur
        cat = await classify_app(db, r.get("process_name", ""))
        if cat == "work":
            work_seconds += dur
        elif cat == "leisure":
            leisure_seconds += dur

    for r in mobile_records:
        dur = r.get("duration_s") or 0
        total_seconds += dur
        cat = await classify_app(db, r.get("package") or r.get("app_name", ""))
        if cat == "work":
            work_seconds += dur
        elif cat == "leisure":
            leisure_seconds += dur

    focus_ratio = work_seconds / max(total_seconds, 1)
    focus_score = min(focus_ratio * 100 / 0.6, 100)  # 60% work = 100 score

    # === Component 2: Deep Work Blocks (30%) ===
    deep_blocks = 0
    for r in pc_records:
        dur = r.get("duration_s") or 0
        if not r.get("idle") and dur >= DEEP_WORK_MIN_SECONDS:
            cat = await classify_app(db, r.get("process_name", ""))
            if cat == "work":
                deep_blocks += 1

    deep_score = min(deep_blocks * 25, 100)

    # === Component 3: Task Completion (20%) ===
    task_score = min(len(tasks_today) * 20, 100)

    # === Component 4: Promise Fulfillment (10%) ===
    total_promises = len(done_promises) + len(overdue_promises)
    promise_rate = len(done_promises) / max(total_promises, 1)
    promise_score = promise_rate * 100

    # === Weighted Total ===
    total_score = (
        focus_score * 0.4
        + deep_score * 0.3
        + task_score * 0.2
        + promise_score * 0.1
    )

    insights = _generate_insights(
        total_score, focus_ratio, deep_blocks, len(tasks_today),
        work_seconds, leisure_seconds, total_seconds,
    )

    return {
        "date": date,
        "score": round(total_score, 1),
        "grade": _score_to_grade(total_score),
        "components": {
            "focus": {"score": round(focus_score, 1), "weight": 0.4,
                      "work_s": work_seconds, "leisure_s": leisure_seconds, "total_s": total_seconds},
            "deep_work": {"score": round(deep_score, 1), "weight": 0.3,
                          "blocks": deep_blocks},
            "tasks": {"score": round(task_score, 1), "weight": 0.2,
                      "completed": len(tasks_today)},
            "promises": {"score": round(promise_score, 1), "weight": 0.1,
                         "fulfilled": len(done_promises), "overdue": len(overdue_promises)},
        },
        "insights": insights,
    }


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _generate_insights(
    score: float, focus_ratio: float, deep_blocks: int,
    tasks_done: int, work_s: int, leisure_s: int, total_s: int,
) -> list[str]:
    """Generate positive, non-judgmental insights."""
    insights = []

    if total_s == 0:
        insights.append("오늘 아직 기록된 활동이 없습니다.")
        return insights

    if focus_ratio >= 0.7:
        insights.append("오늘 집중도가 매우 높았습니다.")
    elif focus_ratio >= 0.5:
        insights.append("업무와 휴식의 밸런스가 적절했습니다.")
    elif total_s > 0:
        insights.append("오늘은 여유로운 하루였습니다.")

    if deep_blocks >= 4:
        insights.append(f"딥 워크 {deep_blocks}회 달성 - 몰입 능력이 뛰어납니다.")
    elif deep_blocks >= 2:
        insights.append(f"25분 이상 집중한 시간이 {deep_blocks}번 있었습니다.")
    elif deep_blocks == 0 and work_s > 3600:
        insights.append("짧은 작업 전환이 많았습니다. 타이머를 활용해보는 건 어떨까요?")

    if tasks_done >= 5:
        insights.append(f"할 일 {tasks_done}개 완료! 생산적인 하루입니다.")
    elif tasks_done > 0:
        insights.append(f"할 일 {tasks_done}개를 완료했습니다.")

    hours = total_s // 3600
    if hours >= 10:
        insights.append(f"오늘 {hours}시간 활동했습니다. 충분한 휴식도 중요합니다.")

    return insights
