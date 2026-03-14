"""Wake word detection - listens for 'Jarvis' (자비스).

Uses Picovoice Porcupine + sounddevice (or pyaudio fallback) for mic input.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)

_PPN_DIR = Path(__file__).resolve().parent.parent

try:
    import pvporcupine
    _HAS_PORCUPINE = True
except ImportError:
    _HAS_PORCUPINE = False

# Prefer sounddevice over pyaudio (easier to install on 3.14)
_AUDIO_BACKEND = None
try:
    import sounddevice as sd
    _AUDIO_BACKEND = "sounddevice"
except ImportError:
    try:
        import pyaudio
        _AUDIO_BACKEND = "pyaudio"
    except ImportError:
        pass


class WakeWordDetector:
    """Listens for a wake word and calls on_detected when triggered."""

    def __init__(
        self,
        access_key: str = "",
        keyword: str = "jarvis",
        keyword_path: str | None = None,
        on_detected: Callable[[], None] | None = None,
    ):
        self.access_key = access_key
        self.keyword = keyword
        self.keyword_path = keyword_path
        self.on_detected = on_detected
        self._running = False
        self._thread: Thread | None = None
        self._porcupine = None

    def start(self) -> None:
        if not _AUDIO_BACKEND:
            logger.warning("No audio backend (sounddevice/pyaudio) - wake word disabled. "
                           "Install: pip install sounddevice")
            return

        if _HAS_PORCUPINE and self.access_key:
            try:
                ppn_path = self.keyword_path
                if not ppn_path:
                    ppn_files = list(_PPN_DIR.glob("*.ppn"))
                    if ppn_files:
                        ppn_path = str(ppn_files[0])

                # Auto-detect Korean model file
                model_path = None
                ko_model = _PPN_DIR / "porcupine_params_ko.pv"
                if ko_model.exists():
                    model_path = str(ko_model)

                if ppn_path:
                    self._porcupine = pvporcupine.create(
                        access_key=self.access_key,
                        keyword_paths=[ppn_path],
                        model_path=model_path,
                    )
                    logger.info("Porcupine initialized with custom keyword: %s", Path(ppn_path).name)
                else:
                    self._porcupine = pvporcupine.create(
                        access_key=self.access_key,
                        keywords=[self.keyword],
                    )
                    logger.info("Porcupine initialized with built-in keyword: %s", self.keyword)
            except Exception:
                logger.exception("Failed to initialize Porcupine")
                self._porcupine = None
        else:
            logger.info("Porcupine not available - set picovoice_access_key in config.json")

        if self._porcupine:
            self._running = True
            self._thread = Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Wake word detector stopped")

    def _listen_loop(self) -> None:
        if not self._porcupine:
            return

        rate = self._porcupine.sample_rate
        frame_len = self._porcupine.frame_length
        logger.info("Listening for wake word (backend=%s, rate=%d)...", _AUDIO_BACKEND, rate)

        if _AUDIO_BACKEND == "sounddevice":
            self._listen_sounddevice(rate, frame_len)
        else:
            self._listen_pyaudio(rate, frame_len)

    def _listen_sounddevice(self, rate: int, frame_len: int) -> None:
        import sounddevice as sd
        import numpy as np

        with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                            blocksize=frame_len) as stream:
            while self._running:
                try:
                    data, _ = stream.read(frame_len)
                    pcm = tuple(data[:, 0])
                    result = self._porcupine.process(pcm)
                    if result >= 0:
                        logger.info("Wake word detected!")
                        if self.on_detected:
                            self.on_detected()
                except Exception:
                    if self._running:
                        logger.exception("Wake word listen error")

    def _listen_pyaudio(self, rate: int, frame_len: int) -> None:
        import pyaudio

        pa = pyaudio.PyAudio()
        stream = pa.open(rate=rate, channels=1, format=pyaudio.paInt16,
                         input=True, frames_per_buffer=frame_len)
        try:
            while self._running:
                try:
                    pcm = stream.read(frame_len, exception_on_overflow=False)
                    pcm_unpacked = struct.unpack_from("h" * frame_len, pcm)
                    result = self._porcupine.process(pcm_unpacked)
                    if result >= 0:
                        logger.info("Wake word detected!")
                        if self.on_detected:
                            self.on_detected()
                except Exception:
                    if self._running:
                        logger.exception("Wake word listen error")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def simulate_detection(self) -> None:
        """Manually trigger wake word detection (for testing/keyboard shortcut)."""
        logger.info("Wake word manually triggered")
        if self.on_detected:
            self.on_detected()
