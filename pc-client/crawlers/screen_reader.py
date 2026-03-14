"""Screen text extraction via Windows UIAutomation API.

Extracts visible text from the active window WITHOUT screenshots or OCR.
Privacy-first: text only, no images captured.

This is what makes J.A.R.V.I.S able to read ANY app (email, SAP, browser)
without needing specific API integrations.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from threading import Thread
from typing import Any

logger = logging.getLogger(__name__)

try:
    import uiautomation as auto
    _HAS_UIA = True
except ImportError:
    _HAS_UIA = False
    logger.warning("uiautomation not installed - screen reading disabled")

# Safety: skip windows containing these keywords (case-insensitive)
_SENSITIVE_KEYWORDS = [
    "password", "비밀번호", "passwd", "credential", "sign in", "sign-in",
    "로그인", "login", "log in", "인증", "otp", "2fa", "two-factor",
    "secret", "private key", "토큰", "token", "비밀",
]

MAX_TEXT_LENGTH = 2000
SIMILARITY_THRESHOLD = 0.90


def _is_sensitive_window(title: str) -> bool:
    """Check if window likely contains sensitive info."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in _SENSITIVE_KEYWORDS)


def _extract_texts_from_control(control, depth: int = 0, max_depth: int = 8) -> list[str]:
    """Recursively extract text from UI control tree."""
    if depth > max_depth:
        return []

    texts = []

    try:
        # Get this control's Name
        name = control.Name
        if name and len(name.strip()) > 1:
            texts.append(name.strip())

        # Try to get Value pattern (text fields, edit boxes)
        try:
            val = control.GetValuePattern()
            if val and val.Value and val.Value.strip():
                texts.append(val.Value.strip())
        except Exception:
            pass

        # Try to get Text pattern (rich text controls, document areas)
        try:
            tp = control.GetTextPattern()
            if tp:
                doc_text = tp.DocumentRange.GetText(2000)
                if doc_text and len(doc_text.strip()) > 3:
                    texts.append(doc_text.strip())
        except Exception:
            pass

        # Recurse into children — browser content lives deep
        children = control.GetChildren()
        if children:
            for child in children[:80]:
                texts.extend(_extract_texts_from_control(child, depth + 1, max_depth))
    except Exception:
        pass

    return texts


def extract_active_window_text(
    exclude_apps: list[str] | None = None,
) -> dict[str, Any] | None:
    """Extract text from the currently active window.

    Returns: {app_name, window_title, extracted_text, text_length} or None
    """
    if not _HAS_UIA:
        return None

    exclude_apps = [a.lower() for a in (exclude_apps or [])]

    try:
        # Get foreground window
        control = auto.GetForegroundControl()
        if not control:
            return None

        window_title = control.Name or ""
        if not window_title:
            return None

        # Safety check
        if _is_sensitive_window(window_title):
            logger.debug("Skipping sensitive window: %s", window_title[:50])
            return None

        # Get process name
        try:
            pid = control.ProcessId
            import ctypes
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            handle = kernel32.OpenProcess(0x0410, False, pid)  # QUERY_INFO | VM_READ
            if handle:
                buf = ctypes.create_unicode_buffer(260)
                psapi.GetModuleFileNameExW(handle, None, buf, 260)
                kernel32.CloseHandle(handle)
                app_name = buf.value.rsplit("\\", 1)[-1] if buf.value else ""
            else:
                app_name = ""
        except Exception:
            app_name = ""

        # Check exclude list
        if app_name.lower() in exclude_apps:
            return None

        # Extract text elements — browsers need deeper traversal
        is_browser = app_name.lower() in {
            "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe",
        }
        max_depth = 8 if is_browser else 6
        raw_texts = _extract_texts_from_control(control, max_depth=max_depth)

        # Deduplicate while preserving order
        seen = set()
        unique_texts = []
        for t in raw_texts:
            if t not in seen and len(t) > 1:
                seen.add(t)
                unique_texts.append(t)

        # Join and truncate
        full_text = "\n".join(unique_texts)
        if len(full_text) > MAX_TEXT_LENGTH:
            full_text = full_text[:MAX_TEXT_LENGTH] + "..."

        if len(full_text.strip()) < 5:
            return None

        return {
            "app_name": app_name,
            "window_title": window_title,
            "extracted_text": full_text,
            "text_length": len(full_text),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        logger.exception("Screen text extraction error")
        return None


def _similarity(a: str, b: str) -> float:
    """Quick similarity ratio between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:500], b[:500]).ratio()


def _text_hash(text: str) -> int:
    """Fast hash for content-change detection."""
    return hash(text[:1000])


def _get_title_and_app(exclude_apps: list[str] | None = None) -> tuple[str, str] | None:
    """Lightweight check: get only window title + app name (no tree walk)."""
    if not _HAS_UIA:
        return None
    try:
        control = auto.GetForegroundControl()
        if not control:
            return None
        title = control.Name or ""
        if not title or _is_sensitive_window(title):
            return None

        pid = control.ProcessId
        import ctypes
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        handle = kernel32.OpenProcess(0x0410, False, pid)
        app = ""
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleFileNameExW(handle, None, buf, 260)
            kernel32.CloseHandle(handle)
            app = buf.value.rsplit("\\", 1)[-1] if buf.value else ""

        if exclude_apps and app.lower() in [a.lower() for a in exclude_apps]:
            return None

        return title, app
    except Exception:
        return None


class ScreenReader:
    """Two-phase screen reader: lightweight title check + deep text extraction.

    Phase 1 (every interval, ~30s): check window title + app name only.
      - Title changed → immediate full text extraction.
      - Title same → go to Phase 2.

    Phase 2 (same title, every 3rd tick = ~90s): full text extraction + hash compare.
      - Hash different → content changed inside SPA → buffer + send.
      - Hash same → nothing changed → complete skip.

    Plus: 90% similarity check on extracted text as final dedup.
    """

    def __init__(
        self,
        interval: float = 30.0,
        exclude_apps: list[str] | None = None,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ):
        self.interval = interval
        self.exclude_apps = exclude_apps or []
        self.similarity_threshold = similarity_threshold
        self._running = False
        self._thread: Thread | None = None
        self._buffer: list[dict] = []
        # State for two-phase check
        self._last_title: str = ""
        self._last_app: str = ""
        self._last_text: str = ""
        self._last_hash: int = 0
        self._same_title_ticks: int = 0

    def start(self) -> None:
        if not _HAS_UIA:
            logger.warning("Screen reader unavailable - install uiautomation")
            return

        self._running = True
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Screen reader started (interval=%.0fs, 2-phase check)", self.interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Screen reader stopped")

    def drain_buffer(self) -> list[dict]:
        records = self._buffer[:]
        self._buffer.clear()
        return records

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                logger.exception("Screen reader loop error")
            time.sleep(self.interval)

    def _tick(self) -> None:
        # Phase 1: lightweight title + app check
        info = _get_title_and_app(exclude_apps=self.exclude_apps)
        if not info:
            return

        title, app = info
        title_changed = (title != self._last_title or app != self._last_app)

        if title_changed:
            # Window switched → immediate full extraction
            self._last_title = title
            self._last_app = app
            self._same_title_ticks = 0
            self._do_extract()
        else:
            # Same title → Phase 2: only every 3rd tick (~90s)
            self._same_title_ticks += 1
            if self._same_title_ticks % 3 == 0:
                self._do_extract_with_hash()

    def _extract(self) -> dict | None:
        """Extract using unified extractor (CDP for browser, UIA for rest)."""
        try:
            from crawlers.text_extractor import extract_text_sync
            return extract_text_sync(exclude_apps=self.exclude_apps)
        except ImportError:
            return extract_active_window_text(exclude_apps=self.exclude_apps)

    def _do_extract(self) -> None:
        """Full extraction on window change."""
        result = self._extract()
        if not result:
            return

        new_text = result["extracted_text"]

        # Similarity dedup
        if _similarity(new_text, self._last_text) >= self.similarity_threshold:
            logger.debug("Skipping similar text (title changed but content ~same)")
            return

        self._last_text = new_text
        self._last_hash = _text_hash(new_text)
        self._buffer.append(result)
        src = result.get("source", "uia")
        logger.debug("Screen text captured [%s]: %s (%d chars)", src, self._last_title[:40], len(new_text))

    def _do_extract_with_hash(self) -> None:
        """Hash-check extraction for SPA content changes."""
        result = self._extract()
        if not result:
            return

        new_text = result["extracted_text"]
        new_hash = _text_hash(new_text)

        # Hash same → content unchanged → skip
        if new_hash == self._last_hash:
            logger.debug("Hash unchanged, skipping")
            return

        # Hash different → content changed within same window
        if _similarity(new_text, self._last_text) >= self.similarity_threshold:
            self._last_hash = new_hash
            logger.debug("Hash changed but text similar, updating hash only")
            return

        self._last_text = new_text
        self._last_hash = new_hash
        self._buffer.append(result)
        src = result.get("source", "uia")
        logger.debug("SPA change [%s]: %s (%d chars)", src, self._last_title[:40], len(new_text))
