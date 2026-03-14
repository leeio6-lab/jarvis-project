"""Scheduled job — generates morning briefing.

Can be triggered by scheduler or manually via API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from server.agents.briefing import BriefingAgent
from server.crawlers.calendar_crawler import sync_calendar
from server.crawlers.gmail_crawler import sync_emails
from server.database import crud
from server.database.db import get_db

logger = logging.getLogger(__name__)


async def run_morning_briefing(locale: str = "ko") -> str:
    """Execute the full morning briefing pipeline:
    1. Sync Gmail (unreplied emails)
    2. Sync Calendar (today's events)
    3. Generate briefing from all data sources
    """
    db = get_db()

    # Get google token if available
    user_state = await crud.get_user_state(db)
    google_token = user_state.get("google_token") if user_state else None

    # Sync external data sources
    logger.info("Morning briefing: syncing data sources...")
    await sync_emails(db, google_token=google_token)
    await sync_calendar(db, google_token=google_token)

    # Generate comprehensive briefing
    agent = BriefingAgent()
    context = {"db": db, "locale": locale}
    briefing = await agent.generate_briefing(context, briefing_type="morning")

    logger.info("Morning briefing generated: %d chars", len(briefing))
    return briefing
