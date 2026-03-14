"""POST /api/v1/command — voice/text command routing through the orchestrator."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.api.schemas import CommandRequest, CommandResponse
from server.core.context_manager import build_context
from server.core.orchestrator import handle_message
from server.database.db import get_db

router = APIRouter(prefix="/api/v1", tags=["command"])


@router.post("/command", response_model=CommandResponse)
async def command(req: CommandRequest):
    db = get_db()
    context = await build_context(db, history=req.history, locale=req.locale)
    reply = await handle_message(req.text, context)
    return CommandResponse(reply=reply)
