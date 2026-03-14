"""POST /api/v1/upload - audio file upload -> preprocess -> STT -> promise extraction pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, UploadFile

from server.analytics.promise_tracker import process_transcript_promises
from server.audio.preprocessor import preprocess
from server.audio.stt import transcribe
from server.database import crud
from server.database.db import get_db

router = APIRouter(prefix="/api/v1", tags=["upload"])


@router.post("/upload/audio")
async def upload_audio(
    file: UploadFile,
    source: str = Query(default="upload", description="mic | call | upload"),
    language: str = Query(default="ko"),
    extract_promises: bool = Query(default=True, description="Auto-extract promises from transcript"),
):
    """Full recording pipeline:
    1. Preprocess audio (normalize, remove silence, split chunks)
    2. Transcribe each chunk via Deepgram
    3. Save transcript to DB
    4. Extract promises from transcript (Claude Haiku)
    5. Return transcript + promises
    """
    audio_data = await file.read()
    mime_type = file.content_type or "audio/wav"
    now = datetime.now(timezone.utc).isoformat()

    # Step 1: Preprocess (if WAV)
    if "wav" in mime_type:
        chunks = preprocess(audio_data)
    else:
        chunks = [audio_data]

    # Step 2: Transcribe all chunks
    all_text = []
    total_duration = 0.0
    for chunk in chunks:
        result = await transcribe(chunk, language=language, mime_type=mime_type)
        text = result.get("text", "")
        if text:
            all_text.append(text)
        dur = result.get("duration_s")
        if dur:
            total_duration += dur

    full_text = " ".join(all_text)

    if not full_text.strip():
        return {
            "transcript_id": None,
            "text": "",
            "promises": [],
            "message": "No speech detected",
        }

    # Step 3: Save transcript
    db = get_db()
    transcript_id = await crud.insert_transcript(
        db,
        source=source,
        text=full_text,
        language=language,
        duration_s=total_duration or None,
        recorded_at=now,
    )

    # Step 4: Extract promises
    promises = []
    if extract_promises:
        promises = await process_transcript_promises(db, transcript_id, full_text)

    return {
        "transcript_id": transcript_id,
        "text": full_text,
        "language": language,
        "duration_s": total_duration or None,
        "chunks_processed": len(chunks),
        "promises": promises,
    }
