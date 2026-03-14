"""Claude Code agent - receives code execution requests and dispatches to PC client via WebSocket.

Flow:
1. User asks J.A.R.V.I.S to code something
2. Orchestrator routes to this agent
3. Agent sends task to connected PC client via WebSocket
4. PC client runs claude-code CLI (executor.py)
5. Result is sent back via WebSocket
6. Agent formats and returns the result
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from server.agents.base import BaseAgent

logger = logging.getLogger(__name__)

# Connected PC client WebSocket - set by the WebSocket handler
_pc_connection = None
_pending_requests: dict[str, asyncio.Future] = {}
_request_counter = 0


def set_pc_connection(ws) -> None:
    global _pc_connection
    _pc_connection = ws


def clear_pc_connection() -> None:
    global _pc_connection
    _pc_connection = None


def is_pc_connected() -> bool:
    return _pc_connection is not None


async def send_to_pc(request_id: str, task: str, working_dir: str | None = None) -> dict[str, Any]:
    """Send a claude-code task to the connected PC client and wait for result."""
    if not is_pc_connected():
        return {"success": False, "error": "PC client is not connected"}

    future: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_requests[request_id] = future

    try:
        await _pc_connection.send_json({
            "type": "claude_code_request",
            "request_id": request_id,
            "task": task,
            "working_dir": working_dir,
        })
        result = await asyncio.wait_for(future, timeout=660.0)  # 600s exec + 60s buffer
        return result
    except asyncio.TimeoutError:
        return {"success": False, "error": "Claude Code execution timed out (660s)"}
    finally:
        _pending_requests.pop(request_id, None)


def handle_pc_response(data: dict[str, Any]) -> None:
    """Called when PC client sends back a claude-code result."""
    request_id = data.get("request_id")
    if request_id and request_id in _pending_requests:
        _pending_requests[request_id].set_result(data)


class ClaudeCodeAgent(BaseAgent):
    name = "claude_code"

    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        if not is_pc_connected():
            return "PC 클라이언트가 연결되어 있지 않습니다. pc-client를 실행해 주세요."

        global _request_counter
        _request_counter += 1
        request_id = f"cc_{_request_counter}"

        result = await send_to_pc(
            request_id=request_id,
            task=user_input,
            working_dir=context.get("working_dir"),
        )

        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            return f"Claude Code 실행 실패: {error}"

        output = result.get("output", "")
        cost = result.get("cost_usd")
        duration = result.get("duration_s")

        parts = [output]
        if cost or duration:
            meta = []
            if duration:
                meta.append(f"소요 시간: {duration:.1f}초")
            if cost:
                meta.append(f"비용: ${cost:.4f}")
            parts.append(f"\n({', '.join(meta)})")

        return "\n".join(parts)
