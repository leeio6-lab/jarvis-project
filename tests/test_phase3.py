"""Phase 3 tests - preprocessor, promise tracker, productivity, trends, report."""

import io
import struct
import wave

import pytest

from server.analytics.productivity_score import (
    _generate_insights,
    _score_to_grade,
    calculate_daily_score,
    classify_app,
)
from server.analytics.promise_tracker import (
    _parse_promises,
    extract_promises,
    get_promise_summary,
    process_transcript_promises,
)
from server.analytics.trend_analyzer import weekly_trend
from server.audio.preprocessor import (
    _write_wav,
    preprocess,
    remove_silence,
    split_chunks,
)
from server.database import crud


# ── Audio Preprocessor ─────────────────────────────────────────────────

def _make_wav(duration_s: float = 1.0, frequency: int = 440, rate: int = 16000) -> bytes:
    """Generate a test WAV with a sine tone."""
    import math

    n_samples = int(rate * duration_s)
    samples = []
    for i in range(n_samples):
        val = int(16000 * math.sin(2 * math.pi * frequency * i / rate))
        samples.append(val)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _make_silent_wav(duration_s: float = 1.0, rate: int = 16000) -> bytes:
    """Generate a silent WAV."""
    n_samples = int(rate * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return buf.getvalue()


def test_preprocess_short_audio():
    """Short audio should come back as single chunk."""
    wav = _make_wav(duration_s=2.0)
    chunks = preprocess(wav)
    assert len(chunks) == 1
    assert len(chunks[0]) > 0


def test_preprocess_non_wav():
    """Non-WAV data should be returned as-is."""
    data = b"not a wav file"
    chunks = preprocess(data)
    assert chunks == [data]


def test_remove_silence():
    """Silence removal should reduce the size of mostly-silent audio."""
    # Mix: 1s tone + 2s silence + 1s tone
    import math
    rate = 16000
    tone_samples = [int(16000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)]
    silence_samples = [0] * (rate * 2)
    all_samples = tone_samples + silence_samples + tone_samples

    pcm = struct.pack(f"<{len(all_samples)}h", *all_samples)
    result = remove_silence(pcm, rate)
    # Result should be shorter than original (silence removed)
    assert len(result) < len(pcm)


def test_split_chunks_short():
    """Audio shorter than CHUNK_MAX should not be split."""
    pcm = b"\x00\x00" * 16000 * 60  # 1 minute
    chunks = split_chunks(pcm, rate=16000)
    assert len(chunks) == 1


# ── Promise Tracker ────────────────────────────────────────────────────

def test_parse_promises_json():
    raw = '[{"content": "보고서 제출", "assignee": "김팀장", "due_date": "2026-03-15"}]'
    promises = _parse_promises(raw)
    assert len(promises) == 1
    assert promises[0]["content"] == "보고서 제출"
    assert promises[0]["due_date"] == "2026-03-15"


def test_parse_promises_empty():
    assert _parse_promises("[]") == []


def test_parse_promises_with_text():
    raw = 'Here are the promises:\n[{"content": "미팅 준비", "assignee": null, "due_date": null}]'
    promises = _parse_promises(raw)
    assert len(promises) == 1


def test_parse_promises_invalid():
    assert _parse_promises("not json at all") == []


@pytest.mark.asyncio
async def test_extract_promises_mock(db):
    """Promise extraction with mock Claude should handle gracefully."""
    promises = await extract_promises("금요일까지 보고서 수정해서 보내드리겠습니다")
    # Mock mode returns based on keyword matching
    assert isinstance(promises, list)


@pytest.mark.asyncio
async def test_process_transcript_promises(db):
    """Full pipeline: transcript -> promise extraction -> DB save."""
    tid = await crud.insert_transcript(
        db, text="금요일까지 보고서 제출하겠습니다", recorded_at="2026-03-14T10:00:00",
    )
    saved = await process_transcript_promises(db, tid, "금요일까지 보고서 제출하겠습니다")
    # In mock mode, keyword matching may or may not find promises
    assert isinstance(saved, list)


@pytest.mark.asyncio
async def test_promise_summary(db):
    await crud.insert_promise(db, content="A")
    await crud.insert_promise(db, content="B")
    await crud.update_promise_status(db, 1, "done")

    summary = await get_promise_summary(db)
    assert summary["total"] == 2
    assert summary["done"] >= 1


# ── Productivity Score ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_app_seed(db):
    """Seed categories (excel=work) should be auto-loaded."""
    cat = await classify_app(db, "excel.exe")
    assert cat == "work"


@pytest.mark.asyncio
async def test_classify_app_unknown_falls_back(db):
    """Unknown app should get classified (mock=neutral) and cached in DB."""
    cat = await classify_app(db, "some_random_app.exe")
    assert cat in ("work", "leisure", "neutral")
    # Should be cached in DB now
    cached = await crud.get_app_category(db, "some_random_app.exe")
    assert cached is not None


@pytest.mark.asyncio
async def test_user_override_category(db):
    """User can override AI classification."""
    await crud.upsert_app_category(
        db, app_name="kakaotalk.exe", category="work",
        sub_category="messenger", classified_by="user",
    )
    cat = await crud.get_app_category(db, "kakaotalk.exe")
    assert cat["category"] == "work"
    assert cat["classified_by"] == "user"


def test_score_to_grade():
    assert _score_to_grade(95) == "S"
    assert _score_to_grade(85) == "A"
    assert _score_to_grade(70) == "B"
    assert _score_to_grade(55) == "C"
    assert _score_to_grade(30) == "D"


def test_generate_insights_high_focus():
    insights = _generate_insights(90, 0.8, 5, 6, 3600, 300, 4200)
    assert any("집중도" in i for i in insights)


def test_generate_insights_no_activity():
    insights = _generate_insights(0, 0, 0, 0, 0, 0, 0)
    assert any("활동이 없" in i for i in insights)


@pytest.mark.asyncio
async def test_calculate_daily_score(db):
    # Seed some work activity
    await crud.insert_pc_activity(
        db, window_title="VSCode", process_name="Code.exe",
        started_at="2026-03-14T09:00:00", duration_s=7200,
    )
    await crud.insert_task(db, title="Done task")
    await crud.update_task(db, 1, status="done")

    score = await calculate_daily_score(db, date="2026-03-14")
    assert "score" in score
    assert "grade" in score
    assert "components" in score
    assert "insights" in score
    assert 0 <= score["score"] <= 100


# ── Trend Analyzer ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_trend_empty_db(db):
    trend = await weekly_trend(db)
    assert "daily_breakdown" in trend
    assert "comparison" in trend
    assert "top_apps" in trend
    assert "promises" in trend


@pytest.mark.asyncio
async def test_weekly_trend_with_data(db):
    await crud.insert_pc_activity(
        db, window_title="VSCode", process_name="Code.exe",
        started_at="2026-03-14T09:00:00", duration_s=3600,
    )
    await crud.insert_app_usage(
        db, device="mobile", package="com.slack", app_name="Slack",
        started_at="2026-03-14T10:00:00", duration_s=600,
    )

    trend = await weekly_trend(db)
    assert trend["comparison"]["total_active"]["this_week"] > 0


# ── API Endpoints ──────────────────────────────────────────────────────

def test_productivity_score_endpoint(client):
    resp = client.get("/api/v1/data/productivity/score")
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "grade" in data


def test_weekly_trend_endpoint(client):
    resp = client.get("/api/v1/data/trends/weekly")
    assert resp.status_code == 200
    data = resp.json()
    assert "comparison" in data


def test_promise_summary_endpoint(client):
    resp = client.get("/api/v1/data/promises/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "completion_rate" in data


def test_weekly_report_endpoint(client):
    resp = client.post("/api/v1/data/report/weekly?locale=ko")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "weekly"
    assert len(data["content"]) > 0


def test_drive_save_endpoint(client):
    # First create a briefing
    client.post("/api/v1/data/briefing", json={"type": "morning", "locale": "ko"})
    # Then try to save it
    resp = client.post("/api/v1/data/drive/save?filename=test.md&content_type=briefing")
    assert resp.status_code == 200


def test_upload_audio_pipeline(client):
    """Test the full upload -> STT -> promise extraction pipeline."""
    wav = _make_wav(duration_s=1.0)
    resp = client.post(
        "/api/v1/upload/audio?source=mic&language=ko",
        files={"file": ("test.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "transcript_id" in data
    assert "text" in data
    assert "promises" in data
