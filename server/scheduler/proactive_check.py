"""Scheduled job - periodic proactive check (30min-1hr interval).

Runs all proactive checks and stores new alerts.
Can be triggered manually via API or runs as a background task.
"""

from __future__ import annotations

import asyncio
import logging

from server.agents.proactive import run_proactive_check
from server.database.db import get_db

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def _proactive_loop(interval_minutes: int = 30) -> None:
    """Background loop that runs proactive checks periodically."""
    logger.info("Proactive check loop started (interval: %dm)", interval_minutes)
    while True:
        try:
            await asyncio.sleep(interval_minutes * 60)
            db = get_db()
            alerts = await run_proactive_check(db)
            if alerts:
                logger.info("Proactive check: %d new alerts generated", len(alerts))
        except asyncio.CancelledError:
            logger.info("Proactive check loop cancelled")
            break
        except Exception:
            logger.exception("Proactive check loop error")


def start_proactive_scheduler(interval_minutes: int = 30) -> None:
    """Start the proactive check background task."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_proactive_loop(interval_minutes))


def stop_proactive_scheduler() -> None:
    """Stop the proactive check background task."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        _task = None
