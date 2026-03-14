"""Audio playback - plays TTS responses using edge-tts + pyaudio (or fallback)."""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import edge_tts
    _HAS_EDGE_TTS = True
except ImportError:
    _HAS_EDGE_TTS = False

DEFAULT_VOICE_KO = "ko-KR-SunHiNeural"
DEFAULT_VOICE_EN = "en-US-AriaNeural"


def _get_voice(locale: str) -> str:
    return DEFAULT_VOICE_KO if locale.startswith("ko") else DEFAULT_VOICE_EN


async def synthesize_and_play(
    text: str,
    locale: str = "ko",
    voice: str | None = None,
) -> None:
    """Convert text to speech and play it immediately."""
    if not _HAS_EDGE_TTS:
        logger.warning("edge-tts not installed - TTS unavailable")
        logger.info("[TTS] %s", text)
        return

    voice = voice or _get_voice(locale)
    communicate = edge_tts.Communicate(text, voice)

    # Write to temp file, then play
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    await communicate.save(tmp_path)
    logger.info("TTS audio saved: %s (%d chars)", tmp_path, len(text))

    # Play audio - try multiple methods
    played = False

    # Method 1: Windows built-in PlaySound (via winsound)
    if not played:
        try:
            # Convert mp3 to wav for winsound (or use ffplay/mpv if available)
            import subprocess
            # Try ffplay (comes with ffmpeg)
            proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait(timeout=60)
            played = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Method 2: Use powershell to play
    if not played:
        try:
            import subprocess
            ps_cmd = (
                f'Add-Type -AssemblyName PresentationCore; '
                f'$player = New-Object System.Windows.Media.MediaPlayer; '
                f'$player.Open([uri]"{tmp_path}"); '
                f'$player.Play(); '
                f'Start-Sleep -Seconds ([math]::Ceiling($player.NaturalDuration.TimeSpan.TotalSeconds + 1)); '
                f'$player.Close()'
            )
            proc = subprocess.Popen(
                ["powershell", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait(timeout=60)
            played = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not played:
        logger.warning("No audio player available. Install ffmpeg or use Windows Media Player.")
        logger.info("[TTS would say]: %s", text[:100])

    # Cleanup
    try:
        Path(tmp_path).unlink(missing_ok=True)
    except OSError:
        pass
