"""POST /api/v1/push — mobile/PC client data push endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from server.api.schemas import (
    PcActivityRecord,
    PushActivityRequest,
    PushPcActivityRequest,
    PushResponse,
    PushScreenTextRequest,
    TaskCreate,
    TaskUpdate,
)
from server.crawlers.mobile_activity import (
    ingest_app_usage_batch,
    ingest_call_logs,
    ingest_location_batch,
)
from server.database import crud
from server.database.db import get_db

router = APIRouter(prefix="/api/v1/push", tags=["push"])


@router.post("/activity", response_model=PushResponse)
async def push_mobile_activity(req: PushActivityRequest):
    """Receive mobile activity data from companion app."""
    db = get_db()
    counts = {}

    if req.app_usage:
        counts["app_usage"] = await ingest_app_usage_batch(
            db, [r.model_dump() for r in req.app_usage]
        )
    if req.call_logs:
        counts["call_logs"] = await ingest_call_logs(
            db, [r.model_dump() for r in req.call_logs]
        )
    if req.locations:
        counts["locations"] = await ingest_location_batch(
            db, [r.model_dump() for r in req.locations]
        )

    return PushResponse(ingested=counts)


@router.post("/pc-activity", response_model=PushResponse)
async def push_pc_activity(req: PushPcActivityRequest):
    """Receive PC activity data from pc-client."""
    db = get_db()
    count = 0
    for r in req.activities:
        await crud.insert_pc_activity(
            db,
            window_title=r.window_title,
            process_name=r.process_name,
            url=r.url,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_s=r.duration_s,
            idle=r.idle,
        )
        count += 1
    return PushResponse(ingested={"pc_activity": count})


@router.post("/tasks")
async def create_task(req: TaskCreate):
    db = get_db()
    task_id = await crud.insert_task(
        db,
        title=req.title,
        description=req.description,
        due_date=req.due_date,
        priority=req.priority,
    )
    return {"task_id": task_id, "message": "할 일이 생성되었습니다"}


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, req: TaskUpdate):
    db = get_db()
    updates = req.model_dump(exclude_none=True)
    ok = await crud.update_task(db, task_id, **updates)
    if not ok:
        return {"success": False, "message": "할 일을 찾을 수 없습니다"}
    return {"success": True, "message": "할 일이 수정되었습니다"}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    db = get_db()
    ok = await crud.delete_task(db, task_id)
    if not ok:
        return {"success": False, "message": "할 일을 찾을 수 없습니다"}
    return {"success": True, "message": "할 일이 삭제되었습니다"}


@router.post("/screen-text", response_model=PushResponse)
async def push_screen_text(req: PushScreenTextRequest):
    """Receive screen text extractions from PC client."""
    db = get_db()
    count = 0
    for r in req.records:
        await crud.insert_screen_text(
            db,
            app_name=r.app_name,
            window_title=r.window_title,
            extracted_text=r.extracted_text,
            text_length=r.text_length,
            timestamp=r.timestamp,
        )
        count += 1
    return PushResponse(ingested={"screen_text": count})
