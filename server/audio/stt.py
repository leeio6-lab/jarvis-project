"""Speech-to-text via Deepgram Nova-3 API.

Falls back to mock transcription when DEEPGRAM_API_KEY is not configured.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from server.config.settings import settings

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


async def transcribe(
    audio_data: bytes,
    *,
    language: str = "ko",
    model: str = "nova-3",
    mime_type: str = "audio/wav",
) -> dict[str, str | float | None]:
    """Transcribe audio bytes. Returns {text, language, duration_s, confidence}."""
    if not settings.has_deepgram:
        logger.warning("Deepgram API key not configured — returning mock transcription")
        return {
            "text": "[MOCK] 음성 인식 결과입니다. Deepgram API 키를 설정하면 실제 음성이 변환됩니다.",
            "language": language,
            "duration_s": None,
            "confidence": None,
        }

    params = {
        "model": model,
        "language": language,
        "smart_format": "true",
        "punctuate": "true",
        "diarize": "true",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DEEPGRAM_URL,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": mime_type,
            },
            params=params,
            content=audio_data,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", {})
    channels = results.get("channels", [{}])
    alt = channels[0].get("alternatives", [{}])[0] if channels else {}
    metadata = results.get("metadata", {})

    return {
        "text": alt.get("transcript", ""),
        "language": language,
        "duration_s": metadata.get("duration"),
        "confidence": alt.get("confidence"),
    }


async def transcribe_file(
    file_path: str | Path,
    *,
    language: str = "ko",
) -> dict[str, str | float | None]:
    """Convenience: transcribe from a file path."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    mime_map = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
    mime_type = mime_map.get(suffix, "audio/wav")
    audio_data = path.read_bytes()
    return await transcribe(audio_data, language=language, mime_type=mime_type)
