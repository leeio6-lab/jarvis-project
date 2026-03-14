"""Voice session manager - orchestrates listen -> STT -> agent -> TTS flow.

Coordinates the complete voice interaction cycle:
1. Wake word detected (or manual trigger)
2. Record audio until silence
3. Send to server for STT + command processing
4. Play TTS response
"""

from __future__ import annotations

import asyncio
import logging

from voice.listener import AudioListener
from voice.speaker import synthesize_and_play

logger = logging.getLogger(__name__)


class VoiceSession:
    """Manages a single voice interaction session."""

    def __init__(self, server_sync, deepgram_api_key: str = "", locale: str = "ko"):
        self.server_sync = server_sync
        self.locale = locale
        self.listener = AudioListener(deepgram_api_key=deepgram_api_key)
        self._active = False

    async def start_session(self) -> None:
        """Run a complete voice interaction cycle."""
        if self._active:
            logger.warning("Session already active")
            return

        self._active = True
        logger.info("Voice session started")

        try:
            await synthesize_and_play("네, 말씀하세요.", self.locale)

            audio = await asyncio.get_event_loop().run_in_executor(
                None, self.listener.record_until_silence
            )

            if not audio:
                await synthesize_and_play("음성을 감지하지 못했습니다.", self.locale)
                return

            result = await self.server_sync.upload_audio(audio)
            text = result.get("text", "")

            if not text:
                await synthesize_and_play("음성을 인식하지 못했습니다.", self.locale)
                return

            logger.info("Recognized: %s", text)

            reply = await self.server_sync.send_command(text, self.locale)
            logger.info("Reply: %s", reply[:100])

            await synthesize_and_play(reply, self.locale)

        except Exception:
            logger.exception("Voice session error")
            try:
                await synthesize_and_play("오류가 발생했습니다.", self.locale)
            except Exception:
                pass
        finally:
            self._active = False
            logger.info("Voice session ended")

    @property
    def is_active(self) -> bool:
        return self._active
