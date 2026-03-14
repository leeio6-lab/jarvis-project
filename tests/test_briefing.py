"""Tests for briefing agent — verifies all data sources are gathered."""

import pytest

from server.agents.briefing import BriefingAgent, _gather_briefing_data, _build_context_message
from server.database import crud


@pytest.mark.asyncio
async def test_gather_briefing_data_empty_db(db):
    """Briefing should work even with no data."""
    data = await _gather_briefing_data(db, briefing_type="morning")
    assert data["type"] == "morning"
    assert data["today_activity"]["total_active_s"] == 0
    assert data["upcoming_events"] == []
    assert data["unreplied_emails"] == []
    assert data["pending_promises"] == []


@pytest.mark.asyncio
async def test_gather_briefing_data_with_all_sources(db):
    """Verify briefing gathers data from ALL sources — the key differentiator."""
    # Seed ALL data sources
    await crud.insert_app_usage(
        db, device="mobile", package="com.kakao.talk",
        app_name="KakaoTalk", started_at="2026-03-14T09:00:00", duration_s=1800,
    )
    await crud.insert_pc_activity(
        db, window_title="VSCode", process_name="Code.exe",
        started_at="2026-03-14T09:00:00", duration_s=7200,
    )
    await crud.insert_transcript(
        db, source="mic", text="내일까지 보고서 제출하기로 했습니다",
        summary="보고서 제출 약속", recorded_at="2026-03-14T10:00:00",
    )
    await crud.insert_promise(
        db, content="보고서 제출", due_date="2026-03-15",
    )
    await crud.upsert_email(
        db, gmail_id="test_001", subject="긴급: 회의 안건",
        sender="boss@co.com", received_at="2026-03-14T08:00:00", priority="high",
    )
    await crud.upsert_calendar_event(
        db, google_event_id="evt_001", title="팀 미팅",
        start_time="2026-03-14T14:00:00", end_time="2026-03-14T15:00:00",
    )
    await crud.insert_location(
        db, latitude=37.5665, longitude=126.978, label="사무실",
        recorded_at="2026-03-14T09:00:00",
    )

    data = await _gather_briefing_data(db, briefing_type="morning")

    # Verify ALL sources are present
    assert len(data["mobile_usage_detail"]) > 0, "Mobile usage should be gathered"
    assert len(data["pc_usage_detail"]) > 0, "PC activity should be gathered"
    assert len(data["recent_transcripts"]) > 0, "Transcripts should be gathered"
    assert len(data["pending_promises"]) > 0, "Promises should be gathered"
    assert len(data["unreplied_emails"]) > 0, "Unreplied emails should be gathered"
    assert len(data["upcoming_events"]) > 0, "Calendar events should be gathered"
    assert len(data["locations"]) > 0, "Location data should be gathered"


@pytest.mark.asyncio
async def test_build_context_message_includes_all_sections(db):
    """Verify the context message includes all data sections."""
    # Seed minimal data
    await crud.upsert_email(
        db, gmail_id="t1", subject="Test", sender="a@b.com",
        received_at="2026-03-14T08:00:00",
    )
    await crud.insert_promise(db, content="Do something")
    await crud.upsert_calendar_event(
        db, title="Meeting", start_time="2026-03-14T14:00:00",
    )
    await crud.insert_transcript(
        db, source="call", text="Call with partner",
        recorded_at="2026-03-14T10:00:00",
    )

    data = await _gather_briefing_data(db, briefing_type="morning")
    msg = _build_context_message(data)

    assert "일정" in msg
    assert "미답장 이메일" in msg
    assert "약속 이행 현황" in msg
    assert "활동 요약" in msg
    assert "최근 녹음/통화" in msg


@pytest.mark.asyncio
async def test_briefing_agent_generates_output(db):
    """Briefing agent should produce non-empty output (using mock Claude)."""
    agent = BriefingAgent()
    context = {"db": db, "locale": "ko"}
    result = await agent.generate_briefing(context, briefing_type="morning")
    assert len(result) > 0
    # Should be saved to DB
    briefing = await crud.get_latest_briefing(db, type="morning")
    assert briefing is not None
    assert briefing["content"] == result
