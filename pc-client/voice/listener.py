"""Microphone listener - captures audio after wake word.

Uses sounddevice (preferred) or pyaudio for mic input.
"""

from __future__ import annotations

import io
import logging
import struct
import wave

logger = logging.getLogger(__name__)

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

RATE = 16000
CHANNELS = 1
CHUNK = 1024
MAX_SILENCE_S = 2.0
MAX_RECORD_S = 30.0
ENERGY_THRESHOLD = 500


class AudioListener:
    """Records audio from microphone with silence detection."""

    def __init__(self, deepgram_api_key: str = ""):
        self.deepgram_api_key = deepgram_api_key

    def record_until_silence(
        self,
        silence_threshold: float = MAX_SILENCE_S,
        max_duration: float = MAX_RECORD_S,
    ) -> bytes | None:
        """Record audio until silence is detected. Returns WAV bytes."""
        if not _AUDIO_BACKEND:
            logger.warning("No audio backend - recording unavailable")
            return None

        if _AUDIO_BACKEND == "sounddevice":
            return self._record_sounddevice(silence_threshold, max_duration)
        else:
            return self._record_pyaudio(silence_threshold, max_duration)

    def _record_sounddevice(self, silence_threshold: float, max_duration: float) -> bytes | None:
        import sounddevice as sd
        import numpy as np

        logger.info("Recording (sounddevice, max %.0fs)...", max_duration)
        frames = []
        silent_chunks = 0
        silence_limit = int(silence_threshold * RATE / CHUNK)
        max_chunks = int(max_duration * RATE / CHUNK)

        with sd.InputStream(samplerate=RATE, channels=CHANNELS, dtype="int16",
                            blocksize=CHUNK) as stream:
            for i in range(max_chunks):
                data, _ = stream.read(CHUNK)
                samples = data[:, 0]
                frames.append(samples.tobytes())

                rms = (sum(int(s) ** 2 for s in samples) / CHUNK) ** 0.5
                if rms < ENERGY_THRESHOLD:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_limit and len(frames) > silence_limit:
                    logger.info("Silence detected, stopping")
                    break

        if not frames:
            return None

        return self._to_wav(b"".join(frames))

    def _record_pyaudio(self, silence_threshold: float, max_duration: float) -> bytes | None:
        import pyaudio

        logger.info("Recording (pyaudio, max %.0fs)...", max_duration)
        pa = pyaudio.PyAudio()
        stream = pa.open(rate=RATE, channels=CHANNELS, format=pyaudio.paInt16,
                         input=True, frames_per_buffer=CHUNK)

        frames = []
        silent_chunks = 0
        silence_limit = int(silence_threshold * RATE / CHUNK)
        max_chunks = int(max_duration * RATE / CHUNK)

        try:
            for i in range(max_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                samples = struct.unpack(f"{CHUNK}h", data)
                rms = (sum(s * s for s in samples) / CHUNK) ** 0.5
                if rms < ENERGY_THRESHOLD:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                if silent_chunks >= silence_limit and len(frames) > silence_limit:
                    logger.info("Silence detected, stopping")
                    break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        if not frames:
            return None

        return self._to_wav(b"".join(frames))

    def _to_wav(self, pcm: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(pcm)
        wav = buf.getvalue()
        duration = len(pcm) / (RATE * 2)
        logger.info("Recording complete: %.1fs, %d bytes", duration, len(wav))
        return wav
