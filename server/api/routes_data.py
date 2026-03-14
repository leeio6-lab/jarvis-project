"""GET /api/v1/data — query crawled data, activity summaries, briefings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from server.analytics.activity_analyzer import get_daily_summary, get_period_trend
from server.api.schemas import BriefingRequest, BriefingResponse
from server.agents.briefing import BriefingAgent
from server.database import crud
from server.database.db import get_db

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/activity/summary")
async def activity_summary(date: str | None = None):
    db = get_db()
    return await get_daily_summary(db, date=date)


@router.get("/activity/trend")
async def activity_trend(days: int = Query(default=7, le=90)):
    db = get_db()
    return await get_period_trend(db, days=days)


@router.get("/emails/unreplied")
async def unreplied_emails(limit: int = Query(default=20, le=100)):
    db = get_db()
    emails = await crud.get_unreplied_emails(db, limit=limit)
    return {"emails": emails, "count": len(emails)}


@router.get("/events/upcoming")
async def upcoming_events(days: int = Query(default=7, le=30)):
    db = get_db()
    now = datetime.now(timezone.utc)
    events = await crud.get_upcoming_events(
        db, since=now.isoformat(), until=(now + timedelta(days=days)).isoformat()
    )
    return {"events": events, "count": len(events)}


@router.get("/promises")
async def promises(status: str | None = None):
    db = get_db()
    data = await crud.get_promises(db, status=status)
    return {"promises": data, "count": len(data)}


@router.get("/tasks")
async def tasks(status: str | None = None):
    db = get_db()
    data = await crud.get_tasks(db, status=status)
    return {"tasks": data, "count": len(data)}


@router.get("/transcripts")
async def transcripts(since: str | None = None, limit: int = Query(default=20, le=100)):
    db = get_db()
    data = await crud.get_transcripts(db, since=since, limit=limit)
    return {"transcripts": data, "count": len(data)}


@router.get("/screen-texts")
async def screen_texts(since: str | None = None, limit: int = Query(default=20, le=100)):
    db = get_db()
    data = await crud.get_screen_texts(db, since=since, limit=limit)
    return {"screen_texts": data, "count": len(data)}


@router.post("/briefing", response_model=BriefingResponse)
async def generate_briefing(req: BriefingRequest):
    db = get_db()
    agent = BriefingAgent()
    context = {"db": db, "locale": req.locale}
    content = await agent.generate_briefing(context, briefing_type=req.type)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return BriefingResponse(type=req.type, content=content, date=today)


@router.get("/notifications")
async def notifications(undelivered_only: bool = False):
    db = get_db()
    if undelivered_only:
        data = await crud.get_undelivered_notifications(db)
    else:
        data = await crud.get_recent_notifications(db, limit=50)
    return {"notifications": data, "count": len(data)}


@router.post("/proactive/check")
async def trigger_proactive_check():
    """Manually trigger a proactive check."""
    from server.agents.proactive import run_proactive_check

    db = get_db()
    alerts = await run_proactive_check(db)
    return {"alerts": alerts, "count": len(alerts)}


@router.get("/productivity/score")
async def productivity_score(date: str | None = None):
    from server.analytics.productivity_score import calculate_daily_score

    db = get_db()
    return await calculate_daily_score(db, date=date)


@router.get("/app-categories")
async def app_categories():
    db = get_db()
    cats = await crud.get_all_app_categories(db)
    return {"categories": cats, "count": len(cats)}


@router.put("/app-category")
async def update_app_category(
    app_name: str = Query(...),
    category: str = Query(..., description="work | leisure | neutral"),
    sub_category: str | None = None,
):
    """User override: '자비스, 카카오톡은 업무용이야'"""
    from server.analytics.productivity_score import _cache

    db = get_db()
    await crud.upsert_app_category(
        db, app_name=app_name, category=category,
        sub_category=sub_category, classified_by="user",
    )
    _cache[app_name.lower()] = category
    return {"app_name": app_name, "category": category, "classified_by": "user"}


@router.get("/trends/weekly")
async def weekly_trends(end_date: str | None = None):
    from server.analytics.trend_analyzer import weekly_trend

    db = get_db()
    return await weekly_trend(db, end_date=end_date)


@router.get("/promises/summary")
async def promise_summary():
    from server.analytics.promise_tracker import get_promise_summary

    db = get_db()
    return await get_promise_summary(db)


@router.post("/report/weekly")
async def generate_weekly_report(locale: str = Query(default="ko")):
    from server.agents.report import ReportAgent

    db = get_db()
    agent = ReportAgent()
    context = {"db": db, "locale": locale}
    content = await agent.generate_report(context, report_type="weekly")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"type": "weekly", "content": content, "date": today}


@router.post("/drive/save")
async def save_to_drive(
    filename: str = Query(...),
    content_type: str = Query(default="briefing", description="briefing | report | transcript"),
):
    """Save the latest briefing/report/transcript to Google Drive."""
    from server.crawlers.drive_sync import save_document_to_drive

    db = get_db()
    user_state = await crud.get_user_state(db)
    google_token = user_state.get("google_token") if user_state else None

    # Fetch content based on type
    if content_type == "briefing":
        data = await crud.get_latest_briefing(db, type="morning")
    elif content_type == "report":
        data = await crud.get_latest_briefing(db, type="weekly")
    else:
        transcripts = await crud.get_transcripts(db, limit=1)
        data = transcripts[0] if transcripts else None

    if not data:
        return {"saved": False, "error": f"No {content_type} found"}

    content = data.get("content") or data.get("text", "")
    result = await save_document_to_drive(
        db, google_token=google_token,
        filename=filename, content=content,
    )
    return result
