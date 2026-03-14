"""Receives and stores mobile app usage, notifications, and call logs from companion app.

The mobile companion app pushes data to the server via POST /api/v1/push/activity.
This module validates, normalizes, and persists the data.
"""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from server.database import crud

logger = logging.getLogger(__name__)


async def ingest_app_usage_batch(
    db: aiosqlite.Connection,
    records: list[dict[str, Any]],
) -> int:
    """Ingest a batch of app usage records from the mobile companion.

    Each record: {package, app_name?, started_at, ended_at?, duration_s?}
    Returns: number of records inserted.
    """
    count = 0
    for r in records:
        package = r.get("package")
        if not package:
            logger.warning("Skipping app_usage record without package: %s", r)
            continue
        await crud.insert_app_usage(
            db,
            device="mobile",
            package=package,
            app_name=r.get("app_name"),
            started_at=r["started_at"],
            ended_at=r.get("ended_at"),
            duration_s=r.get("duration_s"),
        )
        count += 1
    logger.info("Ingested %d mobile app_usage records", count)
    return count


async def ingest_call_logs(
    db: aiosqlite.Connection,
    records: list[dict[str, Any]],
) -> int:
    """Ingest call log records as transcripts (source='call').

    Each record: {phone_number, direction, started_at, duration_s, transcript?}
    """
    count = 0
    for r in records:
        text = r.get("transcript", f"Call {r.get('direction', 'unknown')} - {r.get('phone_number', 'unknown')}")
        await crud.insert_transcript(
            db,
            source="call",
            text=text,
            duration_s=r.get("duration_s"),
            recorded_at=r["started_at"],
        )
        count += 1
    logger.info("Ingested %d call log records", count)
    return count


async def ingest_location_batch(
    db: aiosqlite.Connection,
    records: list[dict[str, Any]],
) -> int:
    """Ingest location data from mobile companion.

    Each record: {latitude, longitude, accuracy_m?, label?, recorded_at}
    """
    count = 0
    for r in records:
        await crud.insert_location(
            db,
            latitude=r["latitude"],
            longitude=r["longitude"],
            accuracy_m=r.get("accuracy_m"),
            label=r.get("label"),
            recorded_at=r["recorded_at"],
        )
        count += 1
    logger.info("Ingested %d location records", count)
    return count
