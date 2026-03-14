"""Scheduled job - weekly report generation (Sunday auto-trigger)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from server.agents.report import ReportAgent
from server.database.db import get_db

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def run_weekly_report(locale: str = "ko") -> str:
    """Generate the weekly report."""
    db = get_db()
    agent = ReportAgent()
    context = {"db": db, "locale": locale}
    report = await agent.generate_report(context, report_type="weekly")

    logger.info("Weekly report generated: %d chars", len(report))

    # Optionally save to Drive
    try:
        from server.crawlers.drive_sync import save_document_to_drive
        from server.database import crud

        user_state = await crud.get_user_state(db)
        google_token = user_state.get("google_token") if user_state else None
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await save_document_to_drive(
            db,
            google_token=google_token,
            filename=f"JARVIS_Weekly_Report_{today}.md",
            content=report,
            folder_name="JARVIS Reports",
        )
    except Exception:
        logger.info("Drive save skipped (not configured or failed)")

    return report


async def _weekly_loop() -> None:
    """Background loop that checks if it's Sunday and triggers report."""
    logger.info("Weekly report scheduler started")
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            now = datetime.now(timezone.utc)
            # Sunday (6) at ~18:00 UTC (KST 03:00 Monday, or adjust)
            if now.weekday() == 6 and now.hour == 18:
                logger.info("Sunday trigger: generating weekly report")
                await run_weekly_report()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Weekly report loop error")


def start_weekly_scheduler() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_weekly_loop())


def stop_weekly_scheduler() -> None:
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        _task = None
