"""Monitors file system changes via watchdog.

Tracks file create/modify/delete events in configured directories.
Useful for understanding work patterns (which files are being edited).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False
    logger.warning("watchdog not installed - file tracking disabled")


class _FileEventHandler:
    """Collects file change events into a buffer."""

    if _HAS_WATCHDOG:
        _base = FileSystemEventHandler
    else:
        _base = object

    def __init__(self, buffer: list[dict], ignore_patterns: list[str] | None = None):
        if _HAS_WATCHDOG:
            super().__init__()
        self._buffer = buffer
        self._ignore = set(ignore_patterns or [
            "__pycache__", ".git", "node_modules", ".venv",
            ".pyc", ".pyo", ".tmp", ".log", "~",
        ])

    def _should_ignore(self, path: str) -> bool:
        return any(ign in path for ign in self._ignore)

    def _record(self, event_type: str, path: str) -> None:
        if self._should_ignore(path):
            return
        self._buffer.append({
            "event": event_type,
            "path": path,
            "filename": Path(path).name,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    def on_created(self, event):
        if not event.is_directory:
            self._record("created", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._record("modified", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._record("deleted", event.src_path)


# Create the actual handler class with proper inheritance
if _HAS_WATCHDOG:
    class FileEventHandler(FileSystemEventHandler):
        def __init__(self, buffer, ignore_patterns=None):
            super().__init__()
            self._handler = _FileEventHandler(buffer, ignore_patterns)

        def on_created(self, event):
            self._handler.on_created(event)

        def on_modified(self, event):
            self._handler.on_modified(event)

        def on_deleted(self, event):
            self._handler.on_deleted(event)


class FileTracker:
    """Watches directories for file changes."""

    def __init__(self, directories: list[str] | None = None):
        self.directories = directories or []
        self._buffer: list[dict] = []
        self._observer = None

    def start(self) -> None:
        if not _HAS_WATCHDOG:
            logger.warning("File tracking unavailable - install watchdog")
            return

        if not self.directories:
            logger.info("No directories configured for file tracking")
            return

        self._observer = Observer()
        handler = FileEventHandler(self._buffer)

        for d in self.directories:
            path = Path(d)
            if path.exists() and path.is_dir():
                self._observer.schedule(handler, str(path), recursive=True)
                logger.info("Watching directory: %s", path)
            else:
                logger.warning("Directory not found, skipping: %s", d)

        self._observer.start()
        logger.info("File tracker started (%d directories)", len(self.directories))

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=10)
            logger.info("File tracker stopped")

    def drain_buffer(self) -> list[dict]:
        """Return and clear accumulated file events."""
        events = self._buffer[:]
        self._buffer.clear()
        return events
