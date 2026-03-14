"""Google Drive sync - file metadata sync + document upload/save.

Phase 3 expansion: save transcripts, briefings, and reports to Drive.
This is key for zero-server-retention security: process on server, save to
user's Drive, delete from server.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from server.config.settings import settings
from server.database import crud

logger = logging.getLogger(__name__)


async def _fetch_files_google(token: str, max_results: int = 30) -> list[dict[str, Any]]:
    """Fetch recently modified files from Google Drive."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "pageSize": max_results,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,size,webViewLink,parents)",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        items = resp.json().get("files", [])

    return [
        {
            "google_file_id": f["id"],
            "name": f["name"],
            "mime_type": f.get("mimeType"),
            "size_bytes": int(f["size"]) if f.get("size") else None,
            "web_link": f.get("webViewLink"),
            "parent_id": f["parents"][0] if f.get("parents") else None,
        }
        for f in items
    ]


def _mock_files() -> list[dict[str, Any]]:
    return [
        {
            "google_file_id": "mock_file_001",
            "name": "Q1 보고서.docx",
            "mime_type": "application/vnd.google-apps.document",
            "size_bytes": 245000,
            "web_link": None,
            "parent_id": None,
        },
    ]


async def sync_drive(
    db: aiosqlite.Connection,
    google_token: str | None = None,
    max_results: int = 30,
) -> dict[str, int]:
    """Sync Google Drive file metadata to local DB."""
    if google_token and settings.has_google:
        try:
            files = await _fetch_files_google(google_token, max_results)
        except Exception:
            logger.exception("Drive API fetch failed, using mock data")
            files = _mock_files()
    else:
        logger.info("Google credentials not configured, using mock Drive data")
        files = _mock_files()

    synced = 0
    for f in files:
        await crud.upsert_drive_file(db, **f)
        synced += 1

    logger.info("Drive sync complete: %d files", synced)
    return {"synced": synced}


# ── Document upload to Drive ──────────────────────────────────────────

async def _find_or_create_folder(token: str, folder_name: str) -> str:
    """Find or create a folder in Google Drive. Returns folder ID."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Search for existing folder
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "q": f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "files(id)",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        files = resp.json().get("files", [])

        if files:
            return files[0]["id"]

        # Create folder
        resp = await client.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        folder_id = resp.json()["id"]
        logger.info("Created Drive folder: %s (%s)", folder_name, folder_id)
        return folder_id


async def _upload_to_drive(
    token: str,
    filename: str,
    content: str | bytes,
    mime_type: str = "text/plain",
    folder_id: str | None = None,
) -> dict[str, str]:
    """Upload a file to Google Drive. Returns {id, name, webViewLink}."""
    import httpx

    metadata: dict[str, Any] = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    content_bytes = content.encode("utf-8") if isinstance(content, str) else content

    # Multipart upload
    boundary = "jarvis_upload_boundary"
    body_parts = [
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n",
        __import__("json").dumps(metadata),
        f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n",
    ]
    body = "".join(body_parts).encode("utf-8") + content_bytes + f"\r\n--{boundary}--".encode("utf-8")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()


async def save_document_to_drive(
    db: aiosqlite.Connection,
    google_token: str | None = None,
    *,
    filename: str,
    content: str,
    folder_name: str = "JARVIS",
    mime_type: str = "text/markdown",
) -> dict[str, Any]:
    """Save a document (transcript, briefing, report) to user's Google Drive.

    Returns: {saved: bool, drive_file_id, web_link} or mock result.
    """
    if not google_token or not settings.has_google:
        logger.info("[MOCK] Would save to Drive: %s (%d chars)", filename, len(content))
        # Track in DB as mock
        mock_id = f"mock_save_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        await crud.upsert_drive_file(
            db,
            google_file_id=mock_id,
            name=filename,
            mime_type=mime_type,
            size_bytes=len(content.encode("utf-8")),
        )
        return {"saved": False, "mock": True, "filename": filename}

    try:
        folder_id = await _find_or_create_folder(google_token, folder_name)
        result = await _upload_to_drive(
            google_token, filename, content,
            mime_type=mime_type, folder_id=folder_id,
        )

        # Track in DB
        await crud.upsert_drive_file(
            db,
            google_file_id=result["id"],
            name=result.get("name", filename),
            mime_type=mime_type,
            size_bytes=len(content.encode("utf-8")),
            web_link=result.get("webViewLink"),
        )

        logger.info("Saved to Drive: %s -> %s", filename, result.get("webViewLink", ""))
        return {"saved": True, "drive_file_id": result["id"], "web_link": result.get("webViewLink")}

    except Exception:
        logger.exception("Failed to save to Drive: %s", filename)
        return {"saved": False, "error": "Drive upload failed"}
