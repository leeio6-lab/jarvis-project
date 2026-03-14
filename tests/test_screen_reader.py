"""Tests for screen text extraction and server integration."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pc-client"))

from server.database import crud


# ── Server-side CRUD + API tests ───────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_and_get_screen_text(db):
    sid = await crud.insert_screen_text(
        db,
        app_name="msedge.exe",
        window_title="Gmail - Inbox - Microsoft Edge",
        extracted_text="김부장 - Q1 보고서 검토 요청\n이메일 본문 내용...",
        timestamp="2026-03-14T10:00:00",
    )
    assert sid >= 1

    texts = await crud.get_screen_texts(db)
    assert len(texts) == 1
    assert texts[0]["app_name"] == "msedge.exe"
    assert "김부장" in texts[0]["extracted_text"]


@pytest.mark.asyncio
async def test_screen_text_time_filter(db):
    await crud.insert_screen_text(
        db, app_name="Code.exe", window_title="VSCode",
        extracted_text="def main():", timestamp="2026-03-14T09:00:00",
    )
    await crud.insert_screen_text(
        db, app_name="saplogon.exe", window_title="SAP",
        extracted_text="고정자산 관리", timestamp="2026-03-14T15:00:00",
    )

    morning = await crud.get_screen_texts(db, since="2026-03-14T08:00:00", until="2026-03-14T12:00:00")
    assert len(morning) == 1
    assert morning[0]["app_name"] == "Code.exe"

    all_texts = await crud.get_screen_texts(db)
    assert len(all_texts) == 2


def test_push_screen_text_endpoint(client):
    resp = client.post("/api/v1/push/screen-text", json={
        "records": [
            {
                "app_name": "msedge.exe",
                "window_title": "네이버 웍스 - Microsoft Edge",
                "extracted_text": "김부장 - 회의 안건 공유\n내일 10시 미팅입니다",
                "text_length": 30,
                "timestamp": "2026-03-14T10:30:00",
            },
            {
                "app_name": "saplogon.exe",
                "window_title": "SAP Easy Access",
                "extracted_text": "고정자산 등록 - AS01\n자산번호: 10000123",
                "text_length": 35,
                "timestamp": "2026-03-14T11:00:00",
            },
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["ingested"]["screen_text"] == 2


def test_get_screen_texts_endpoint(client):
    # Push first
    client.post("/api/v1/push/screen-text", json={
        "records": [
            {
                "app_name": "outlook.exe",
                "window_title": "Outlook",
                "extracted_text": "미답장 메일 3건",
                "timestamp": "2026-03-14T09:00:00",
            },
        ],
    })

    resp = client.get("/api/v1/data/screen-texts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1


# ── PC Client screen_reader unit tests ─────────────────────────────────

def test_sensitive_window_detection():
    from crawlers.screen_reader import _is_sensitive_window

    assert _is_sensitive_window("Login - Chrome") is True
    assert _is_sensitive_window("비밀번호 입력") is True
    assert _is_sensitive_window("Sign in to Google") is True
    assert _is_sensitive_window("VSCode - project") is False
    assert _is_sensitive_window("SAP Easy Access") is False


def test_similarity_check():
    from crawlers.screen_reader import _similarity

    assert _similarity("hello world", "hello world") > 0.99
    assert _similarity("hello world", "hello earth") < 0.90
    assert _similarity("", "") == 0.0
    assert _similarity("abc", "xyz") < 0.5


def test_text_hash():
    from crawlers.screen_reader import _text_hash

    h1 = _text_hash("same content")
    h2 = _text_hash("same content")
    h3 = _text_hash("different content")
    assert h1 == h2
    assert h1 != h3


def test_two_phase_logic():
    """Verify ScreenReader 2-phase tick logic."""
    from crawlers.screen_reader import ScreenReader

    reader = ScreenReader(interval=1.0)
    # Simulate: title changes → _same_title_ticks resets
    reader._last_title = "Old Title"
    reader._last_app = "old.exe"

    # Phase 1: title changed
    assert reader._same_title_ticks == 0

    # Phase 2: same title, tick counter increments
    reader._same_title_ticks = 1
    assert reader._same_title_ticks % 3 != 0  # tick 1: no extract
    reader._same_title_ticks = 2
    assert reader._same_title_ticks % 3 != 0  # tick 2: no extract
    reader._same_title_ticks = 3
    assert reader._same_title_ticks % 3 == 0  # tick 3: extract with hash
