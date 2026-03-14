"""Audio preprocessing - VAD silence removal, chunk splitting.

Prepares audio for optimal STT accuracy:
1. Silence removal (energy-based VAD)
2. Long audio splitting into chunks (max 5 min per chunk)
3. Format normalization (to 16kHz mono WAV)
"""

from __future__ import annotations

import io
import logging
import struct
import wave
from typing import Any

logger = logging.getLogger(__name__)

TARGET_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2  # 16-bit
CHUNK_MAX_SECONDS = 300  # 5 minutes per chunk
SILENCE_THRESHOLD_RMS = 200
SILENCE_MIN_DURATION_MS = 500  # min silence gap to cut


def _read_wav(data: bytes) -> tuple[bytes, int, int, int]:
    """Read WAV data, return (pcm_bytes, rate, channels, sample_width)."""
    buf = io.BytesIO(data)
    with wave.open(buf, "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sw = wf.getsampwidth()
        pcm = wf.readframes(wf.getnframes())
    return pcm, rate, channels, sw


def _write_wav(pcm: bytes, rate: int = TARGET_RATE) -> bytes:
    """Write PCM data to WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(TARGET_CHANNELS)
        wf.setsampwidth(TARGET_SAMPLE_WIDTH)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _to_mono_16k(pcm: bytes, rate: int, channels: int, sample_width: int) -> bytes:
    """Convert to mono 16-bit. Simple downmix for stereo. Rate conversion is approximate."""
    # Convert to 16-bit if needed
    if sample_width == 1:
        # 8-bit unsigned to 16-bit signed
        samples = [(b - 128) * 256 for b in pcm]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
    elif sample_width > 2:
        # 24/32-bit: take upper 16 bits
        step = sample_width
        samples = []
        for i in range(0, len(pcm), step * channels):
            val = int.from_bytes(pcm[i + step - 2 : i + step], "little", signed=True)
            samples.append(val)
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        channels = 1

    # Stereo to mono: average channels
    if channels == 2:
        samples_16 = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        mono = []
        for i in range(0, len(samples_16), 2):
            if i + 1 < len(samples_16):
                mono.append((samples_16[i] + samples_16[i + 1]) // 2)
            else:
                mono.append(samples_16[i])
        pcm = struct.pack(f"<{len(mono)}h", *mono)

    # Simple rate conversion (nearest-neighbor resampling)
    if rate != TARGET_RATE:
        samples_16 = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        ratio = TARGET_RATE / rate
        new_len = int(len(samples_16) * ratio)
        resampled = []
        for i in range(new_len):
            src_idx = min(int(i / ratio), len(samples_16) - 1)
            resampled.append(samples_16[src_idx])
        pcm = struct.pack(f"<{len(resampled)}h", *resampled)

    return pcm


def remove_silence(pcm: bytes, rate: int = TARGET_RATE) -> bytes:
    """Remove silent segments from PCM audio (energy-based VAD)."""
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    frame_size = rate // 50  # 20ms frames
    output_samples = []

    for i in range(0, len(samples), frame_size):
        frame = samples[i : i + frame_size]
        if not frame:
            break
        rms = (sum(s * s for s in frame) / len(frame)) ** 0.5
        if rms >= SILENCE_THRESHOLD_RMS:
            output_samples.extend(frame)
        else:
            # Keep a tiny bit of silence for natural speech
            if output_samples and output_samples[-1] != 0:
                silence_pad = [0] * min(frame_size, rate // 10)  # 100ms pad
                output_samples.extend(silence_pad)

    if not output_samples:
        return pcm  # Don't return empty audio

    return struct.pack(f"<{len(output_samples)}h", *output_samples)


def split_chunks(pcm: bytes, rate: int = TARGET_RATE) -> list[bytes]:
    """Split long audio into chunks at silence boundaries."""
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    total_seconds = len(samples) / rate

    if total_seconds <= CHUNK_MAX_SECONDS:
        return [pcm]

    chunks = []
    chunk_samples = CHUNK_MAX_SECONDS * rate
    frame_size = rate // 50

    start = 0
    while start < len(samples):
        end = min(start + chunk_samples, len(samples))

        # Try to find a silence boundary near the end for clean splits
        if end < len(samples):
            search_start = max(end - rate * 5, start)  # search last 5s
            best_split = end
            min_energy = float("inf")

            for j in range(search_start, end, frame_size):
                frame = samples[j : j + frame_size]
                if frame:
                    energy = sum(s * s for s in frame) / len(frame)
                    if energy < min_energy:
                        min_energy = energy
                        best_split = j + frame_size

            end = best_split

        chunk = samples[start:end]
        if chunk:
            chunks.append(struct.pack(f"<{len(chunk)}h", *chunk))
        start = end

    logger.info("Split audio into %d chunks (%.1fs total)", len(chunks), total_seconds)
    return chunks


def preprocess(audio_data: bytes) -> list[bytes]:
    """Full preprocessing pipeline: normalize -> remove silence -> split.

    Args:
        audio_data: Raw WAV bytes

    Returns:
        List of preprocessed WAV chunks ready for STT
    """
    try:
        pcm, rate, channels, sw = _read_wav(audio_data)
    except Exception:
        logger.warning("Could not parse as WAV, returning as-is")
        return [audio_data]

    # Normalize to mono 16kHz 16-bit
    pcm = _to_mono_16k(pcm, rate, channels, sw)

    # Remove silence
    original_len = len(pcm)
    pcm = remove_silence(pcm)
    removed_pct = (1 - len(pcm) / max(original_len, 1)) * 100
    if removed_pct > 5:
        logger.info("Removed %.0f%% silence", removed_pct)

    # Split into chunks
    chunks = split_chunks(pcm)

    # Convert back to WAV
    return [_write_wav(chunk) for chunk in chunks]
