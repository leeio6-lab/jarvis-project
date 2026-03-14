"""Syncs collected PC activity data to the J.A.R.V.I.S server.

Periodically sends buffered window/browser/file tracking data
to the server via POST /api/v1/push/pc-activity.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ServerSync:
    """Manages HTTP sync with the J.A.R.V.I.S server."""

    def __init__(self, server_url: str, sync_interval: float = 60.0):
        self.server_url = server_url.rstrip("/")
        self.sync_interval = sync_interval
        self._client: httpx.AsyncClient | None = None
        self._running = False

    async def start(self) -> None:
        self._client = httpx.AsyncClient(base_url=self.server_url, timeout=30.0)
        self._running = True
        logger.info("Server sync initialized: %s", self.server_url)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def push_pc_activity(self, records: list[dict[str, Any]]) -> bool:
        """Push PC activity records to server."""
        if not records or not self._client:
            return True

        try:
            resp = await self._client.post(
                "/api/v1/push/pc-activity",
                json={"activities": records},
            )
            resp.raise_for_status()
            data = resp.json()
            count = data.get("ingested", {}).get("pc_activity", 0)
            logger.info("Synced %d PC activity records to server", count)
            return True
        except httpx.HTTPError:
            logger.exception("Failed to sync PC activity")
            return False

    async def push_screen_texts(self, records: list[dict[str, Any]]) -> bool:
        """Push screen text records to server."""
        if not records or not self._client:
            return True

        try:
            resp = await self._client.post(
                "/api/v1/push/screen-text",
                json={"records": records},
            )
            resp.raise_for_status()
            count = resp.json().get("ingested", {}).get("screen_text", 0)
            logger.info("Synced %d screen text records to server", count)
            return True
        except httpx.HTTPError:
            logger.exception("Failed to sync screen texts")
            return False

    async def send_command(self, text: str, locale: str = "ko") -> str:
        """Send a text command to the server and get a reply."""
        if not self._client:
            return "Server not connected"

        try:
            resp = await self._client.post(
                "/api/v1/command",
                json={"text": text, "locale": locale},
            )
            resp.raise_for_status()
            return resp.json().get("reply", "")
        except httpx.HTTPError:
            logger.exception("Failed to send command")
            return "Server communication error"

    async def upload_audio(self, audio_data: bytes, filename: str = "recording.wav") -> dict:
        """Upload audio file for transcription."""
        if not self._client:
            return {"error": "Server not connected"}

        try:
            resp = await self._client.post(
                "/api/v1/upload/audio",
                files={"file": (filename, audio_data, "audio/wav")},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            logger.exception("Failed to upload audio")
            return {"error": "Upload failed"}

    async def check_health(self) -> bool:
        """Check server health."""
        if not self._client:
            return False
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
