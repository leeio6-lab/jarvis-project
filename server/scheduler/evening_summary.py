"""Scheduled job — generates evening summary of daily activity."""

from __future__ import annotations

import logging

from server.agents.briefing import BriefingAgent
from server.crawlers.gmail_crawler import sync_emails
from server.database import crud
from server.database.db import get_db

logger = logging.getLogger(__name__)


async def run_evening_summary(locale: str = "ko") -> str:
    """Execute the evening summary pipeline:
    1. Sync email status (check for new replies)
    2. Generate evening summary from all day's data
    """
    db = get_db()

    user_state = await crud.get_user_state(db)
    google_token = user_state.get("google_token") if user_state else None

    # Final email sync for the day
    logger.info("Evening summary: syncing data sources...")
    await sync_emails(db, google_token=google_token)

    # Generate comprehensive evening summary
    agent = BriefingAgent()
    context = {"db": db, "locale": locale}
    briefing = await agent.generate_briefing(context, briefing_type="evening")

    logger.info("Evening summary generated: %d chars", len(briefing))
    return briefing
