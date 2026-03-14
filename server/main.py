"""J.A.R.V.I.S - FastAPI entry point."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from server.agents.claude_code import clear_pc_connection, handle_pc_response, set_pc_connection
from server.api.routes_command import router as command_router
from server.api.routes_data import router as data_router
from server.api.routes_push import router as push_router
from server.api.routes_upload import router as upload_router
from server.config.logging_config import setup_logging
from server.config.settings import settings
from server.database.db import close_db, init_db
from server.scheduler.proactive_check import start_proactive_scheduler, stop_proactive_scheduler
from server.scheduler.weekly_report import start_weekly_scheduler, stop_weekly_scheduler
from server.utils.i18n import t
from shared.constants import APP_VERSION, DEFAULT_LOCALE

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(t("app.startup", settings.app_locale))
    await init_db()
    start_proactive_scheduler(interval_minutes=30)
    start_weekly_scheduler()
    yield
    stop_weekly_scheduler()
    stop_proactive_scheduler()
    logger.info(t("app.shutdown", settings.app_locale))
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version=APP_VERSION,
    lifespan=lifespan,
)

# CORS — allow browser extension to POST to localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(command_router)
app.include_router(data_router)
app.include_router(push_router)
app.include_router(upload_router)


@app.get("/health")
async def health():
    from server.agents.claude_code import is_pc_connected

    return {
        "status": "ok",
        "version": APP_VERSION,
        "message": t("app.health_ok", settings.app_locale),
        "pc_connected": is_pc_connected(),
    }


@app.get("/")
async def root(locale: str = Query(default=DEFAULT_LOCALE)):
    return {"message": t("app.welcome", locale)}


@app.websocket("/ws/pc-client")
async def pc_client_websocket(websocket: WebSocket):
    """WebSocket for PC client bidirectional communication.

    PC client -> server: crawling data, claude-code results
    Server -> PC client: claude-code requests, commands
    """
    await websocket.accept()
    set_pc_connection(websocket)
    logger.info("PC client connected via WebSocket")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "claude_code_result":
                handle_pc_response(data)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                logger.warning("Unknown WebSocket message type: %s", msg_type)
    except WebSocketDisconnect:
        logger.info("PC client disconnected")
    finally:
        clear_pc_connection()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=(settings.app_env == "development"),
    )
