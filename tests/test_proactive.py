"""Tests for proactive agent - the second key differentiator."""

import pytest
from datetime import datetime, timedelta, timezone

from server.agents.proactive import (
    check_overdue_promises,
    check_upcoming_deadlines,
    check_unreplied_emails,
    run_proactive_check,
)
from server.database import crud


@pytest.mark.asyncio
async def test_unreplied_email_alert_high_priority(db):
    """High-priority emails unreplied >24h should trigger alert."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    await crud.upsert_email(
        db, gmail_id="urgent_001", subject="긴급: 서버 장애",
        sender="ops@company.com", received_at=old_time, priority="high",
    )

    alerts = await check_unreplied_emails(db)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "email_remind"
    assert "30시간" in alerts[0]["title"] or "30" in alerts[0]["title"]


@pytest.mark.asyncio
async def test_no_alert_for_recent_email(db):
    """Emails received <24h ago should not trigger alert."""
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await crud.upsert_email(
        db, gmail_id="recent_001", subject="점심 뭐 먹을까",
        sender="friend@gmail.com", received_at=recent, priority="normal",
    )

    alerts = await check_unreplied_emails(db)
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_deadline_alert(db):
    """Tasks due within 24h should trigger alert."""
    due = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    await crud.insert_task(
        db, title="PR 리뷰 완료", due_date=due, priority="high",
    )

    alerts = await check_upcoming_deadlines(db)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "deadline"
    assert "6시간" in alerts[0]["title"] or "PR 리뷰" in alerts[0]["message"]


@pytest.mark.asyncio
async def test_no_alert_for_far_deadline(db):
    """Tasks due in >24h should not trigger alert."""
    due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    await crud.insert_task(db, title="월간 보고서", due_date=due)

    alerts = await check_upcoming_deadlines(db)
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_overdue_promise_alert(db):
    """Promises past due date should trigger alert and be marked overdue."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pid = await crud.insert_promise(
        db, content="보고서 제출", due_date=yesterday,
    )

    alerts = await check_overdue_promises(db)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "promise_overdue"

    # Should have been marked as overdue in DB
    promises = await crud.get_promises(db, status="overdue")
    assert len(promises) == 1
    assert promises[0]["id"] == pid


@pytest.mark.asyncio
async def test_proactive_check_cooldown(db):
    """Same alert type should not repeat within cooldown period."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    await crud.upsert_email(
        db, gmail_id="cool_001", subject="Test",
        sender="a@b.com", received_at=old_time, priority="high",
    )

    # First check: should generate alert
    alerts1 = await run_proactive_check(db)
    email_alerts1 = [a for a in alerts1 if a["type"] == "email_remind"]
    assert len(email_alerts1) >= 1

    # Second check: should be in cooldown
    alerts2 = await run_proactive_check(db)
    email_alerts2 = [a for a in alerts2 if a["type"] == "email_remind"]
    assert len(email_alerts2) == 0


@pytest.mark.asyncio
async def test_notification_crud(db):
    """Test notification insert and retrieval."""
    nid = await crud.insert_notification(
        db, type="test", title="Test Alert", message="This is a test",
    )
    assert nid >= 1

    notifs = await crud.get_recent_notifications(db, type="test")
    assert len(notifs) == 1
    assert notifs[0]["title"] == "Test Alert"

    undelivered = await crud.get_undelivered_notifications(db)
    assert len(undelivered) == 1

    ok = await crud.mark_notification_delivered(db, nid)
    assert ok

    undelivered = await crud.get_undelivered_notifications(db)
    assert len(undelivered) == 0
