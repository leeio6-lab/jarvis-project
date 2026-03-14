"""Tracks active window title and process via Windows API (ctypes).

Polls GetForegroundWindow every 5 seconds, records window changes.
Uses ctypes directly - no pywin32 dependency required.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from threading import Thread

logger = logging.getLogger(__name__)

# Windows API
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
psapi = ctypes.windll.psapi  # type: ignore[attr-defined]

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def _get_foreground_window_info() -> dict[str, str | int | bool] | None:
    """Get info about the current foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Window title
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    # Process ID
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # Process name
    process_name = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
    if handle:
        try:
            exe_buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleFileNameExW(handle, None, exe_buf, 260)
            full_path = exe_buf.value
            process_name = full_path.rsplit("\\", 1)[-1] if full_path else ""
        finally:
            kernel32.CloseHandle(handle)

    return {
        "window_title": title,
        "process_name": process_name,
        "pid": pid.value,
    }


def _check_idle() -> float:
    """Get seconds since last user input (mouse/keyboard)."""

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime  # type: ignore[attr-defined]
        return millis / 1000.0
    return 0.0


class WindowTracker:
    """Tracks active windows, detects changes, accumulates sessions."""

    def __init__(
        self,
        interval: float = 5.0,
        idle_threshold: float = 300.0,
        on_session_end: Callable | None = None,
    ):
        self.interval = interval
        self.idle_threshold = idle_threshold
        self.on_session_end = on_session_end

        self._current: dict | None = None
        self._session_start: str | None = None
        self._running = False
        self._thread: Thread | None = None
        self._buffer: list[dict] = []

    def start(self) -> None:
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Window tracker started (interval=%.1fs)", self.interval)

    def stop(self) -> None:
        self._running = False
        self._finalize_session()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Window tracker stopped")

    def drain_buffer(self) -> list[dict]:
        """Return and clear accumulated activity records."""
        records = self._buffer[:]
        self._buffer.clear()
        return records

    def _loop(self) -> None:
        while self._running:
            try:
                info = _get_foreground_window_info()
                idle_s = _check_idle()
                is_idle = idle_s >= self.idle_threshold
                now = datetime.now(timezone.utc).isoformat()

                if info is None:
                    time.sleep(self.interval)
                    continue

                # Detect window change or idle transition
                changed = (
                    self._current is None
                    or self._current.get("window_title") != info["window_title"]
                    or self._current.get("process_name") != info["process_name"]
                    or self._current.get("idle", False) != is_idle
                )

                if changed:
                    self._finalize_session()
                    self._current = {**info, "idle": is_idle}
                    self._session_start = now
            except Exception:
                logger.exception("Window tracker error")

            time.sleep(self.interval)

    def _finalize_session(self) -> None:
        if self._current and self._session_start:
            now = datetime.now(timezone.utc).isoformat()
            start = self._session_start
            # Calculate duration
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(now)
                duration_s = int((e - s).total_seconds())
            except ValueError:
                duration_s = 0

            if duration_s >= 2:  # ignore < 2s flickers
                record = {
                    "window_title": self._current["window_title"],
                    "process_name": self._current.get("process_name", ""),
                    "started_at": start,
                    "ended_at": now,
                    "duration_s": duration_s,
                    "idle": self._current.get("idle", False),
                }
                self._buffer.append(record)
                if self.on_session_end:
                    self.on_session_end(record)

            self._current = None
            self._session_start = None
