"""Tests for database CRUD operations."""

import pytest
from server.database import crud


@pytest.mark.asyncio
async def test_insert_and_get_app_usage(db):
    row_id = await crud.insert_app_usage(
        db, device="mobile", package="com.kakao.talk",
        app_name="KakaoTalk", started_at="2026-03-14T09:00:00",
        ended_at="2026-03-14T09:30:00", duration_s=1800,
    )
    assert row_id >= 1
    rows = await crud.get_app_usage(db)
    assert len(rows) == 1
    assert rows[0]["package"] == "com.kakao.talk"
    assert rows[0]["duration_s"] == 1800


@pytest.mark.asyncio
async def test_app_usage_summary(db):
    await crud.insert_app_usage(
        db, device="mobile", package="com.kakao.talk",
        app_name="KakaoTalk", started_at="2026-03-14T09:00:00", duration_s=600,
    )
    await crud.insert_app_usage(
        db, device="mobile", package="com.kakao.talk",
        app_name="KakaoTalk", started_at="2026-03-14T10:00:00", duration_s=300,
    )
    summary = await crud.get_app_usage_summary(
        db, since="2026-03-14T00:00:00", until="2026-03-14T23:59:59",
    )
    assert len(summary) == 1
    assert summary[0]["total_seconds"] == 900
    assert summary[0]["sessions"] == 2


@pytest.mark.asyncio
async def test_pc_activity_crud(db):
    row_id = await crud.insert_pc_activity(
        db, window_title="VSCode - project",
        process_name="Code.exe", started_at="2026-03-14T09:00:00",
        duration_s=3600, idle=False,
    )
    assert row_id >= 1
    rows = await crud.get_pc_activity(db)
    assert len(rows) == 1
    assert rows[0]["process_name"] == "Code.exe"


@pytest.mark.asyncio
async def test_transcript_crud(db):
    tid = await crud.insert_transcript(
        db, source="mic", text="내일 3시까지 보고서 제출해야 합니다",
        summary="보고서 제출 마감", recorded_at="2026-03-14T14:00:00",
    )
    rows = await crud.get_transcripts(db)
    assert len(rows) == 1
    assert rows[0]["id"] == tid


@pytest.mark.asyncio
async def test_promise_lifecycle(db):
    pid = await crud.insert_promise(
        db, content="보고서 제출", assignee="나", due_date="2026-03-15",
    )
    pending = await crud.get_promises(db, status="pending")
    assert len(pending) == 1
    assert pending[0]["content"] == "보고서 제출"

    ok = await crud.update_promise_status(db, pid, "done")
    assert ok
    done = await crud.get_promises(db, status="done")
    assert len(done) == 1


@pytest.mark.asyncio
async def test_email_upsert_and_reply(db):
    await crud.upsert_email(
        db, gmail_id="msg_001", subject="회의 안건",
        sender="boss@co.com", received_at="2026-03-14T08:00:00",
    )
    unreplied = await crud.get_unreplied_emails(db)
    assert len(unreplied) == 1

    ok = await crud.mark_email_replied(db, "msg_001")
    assert ok
    unreplied = await crud.get_unreplied_emails(db)
    assert len(unreplied) == 0


@pytest.mark.asyncio
async def test_calendar_events(db):
    await crud.upsert_calendar_event(
        db, google_event_id="evt_001", title="팀 미팅",
        start_time="2026-03-14T09:00:00", end_time="2026-03-14T10:00:00",
    )
    # Upsert same event with updated title
    await crud.upsert_calendar_event(
        db, google_event_id="evt_001", title="팀 미팅 (변경됨)",
        start_time="2026-03-14T09:00:00", end_time="2026-03-14T10:00:00",
    )
    events = await crud.get_upcoming_events(db)
    assert len(events) == 1
    assert events[0]["title"] == "팀 미팅 (변경됨)"


@pytest.mark.asyncio
async def test_task_lifecycle(db):
    tid = await crud.insert_task(
        db, title="코드 리뷰", priority="high", due_date="2026-03-15",
    )
    tasks = await crud.get_tasks(db, status="pending")
    assert len(tasks) == 1

    ok = await crud.update_task(db, tid, status="done")
    assert ok
    pending = await crud.get_tasks(db, status="pending")
    assert len(pending) == 0
    done = await crud.get_tasks(db, status="done")
    assert len(done) == 1

    ok = await crud.delete_task(db, tid)
    assert ok
    all_tasks = await crud.get_tasks(db)
    assert len(all_tasks) == 0


@pytest.mark.asyncio
async def test_user_state(db):
    state = await crud.get_user_state(db)
    assert state is None

    await crud.upsert_user_state(db, onboarding_stage="api_keys", locale="ko")
    state = await crud.get_user_state(db)
    assert state["onboarding_stage"] == "api_keys"

    await crud.upsert_user_state(db, onboarding_stage="completed")
    state = await crud.get_user_state(db)
    assert state["onboarding_stage"] == "completed"
    assert state["locale"] == "ko"


@pytest.mark.asyncio
async def test_location_crud(db):
    await crud.insert_location(
        db, latitude=37.5665, longitude=126.978, label="office",
        recorded_at="2026-03-14T09:00:00",
    )
    locs = await crud.get_locations(db)
    assert len(locs) == 1
    assert locs[0]["label"] == "office"


@pytest.mark.asyncio
async def test_drive_files(db):
    await crud.upsert_drive_file(
        db, google_file_id="file_001", name="report.docx",
        mime_type="application/vnd.google-apps.document", size_bytes=10000,
    )
    files = await crud.get_drive_files(db)
    assert len(files) == 1
    assert files[0]["name"] == "report.docx"
