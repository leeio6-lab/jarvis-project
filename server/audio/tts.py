"""Text-to-speech via edge-tts (Microsoft Edge TTS — free, no API key needed)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_VOICE_KO = "ko-KR-SunHiNeural"
DEFAULT_VOICE_EN = "en-US-AriaNeural"


def _get_voice(locale: str) -> str:
    return DEFAULT_VOICE_KO if locale.startswith("ko") else DEFAULT_VOICE_EN


async def synthesize(
    text: str,
    *,
    locale: str = "ko",
    voice: str | None = None,
) -> bytes:
    """Convert text to speech, returns audio bytes (MP3)."""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed. Run: pip install edge-tts")
        return b""

    voice = voice or _get_voice(locale)
    communicate = edge_tts.Communicate(text, voice)

    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])

    audio_bytes = buffer.getvalue()
    logger.info("TTS generated %d bytes for %d chars", len(audio_bytes), len(text))
    return audio_bytes


async def synthesize_to_file(
    text: str,
    output_path: str | Path,
    *,
    locale: str = "ko",
    voice: str | None = None,
) -> Path:
    """Convert text to speech and save to file."""
    audio = await synthesize(text, locale=locale, voice=voice)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return path
