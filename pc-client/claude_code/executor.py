"""Claude Code CLI executor - spawns claude-code subprocess on Windows.

Uses subprocess.Popen with CREATE_NEW_PROCESS_GROUP for clean process management.
Timeout: 600 seconds. Output format: JSON.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

# Windows process creation flag
CREATE_NEW_PROCESS_GROUP = 0x00000200


def execute_claude_code(
    task: str,
    working_dir: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run claude-code CLI and return structured result.

    Args:
        task: The coding task to execute
        working_dir: Directory to run in (defaults to cwd)
        timeout: Max execution time in seconds (default 600)

    Returns:
        {success, output, error, duration_s, cost_usd}
    """
    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        task,
    ]

    start_time = time.monotonic()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_dir,
            creationflags=CREATE_NEW_PROCESS_GROUP,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the process group on timeout
            proc.kill()
            proc.communicate(timeout=10)
            duration = time.monotonic() - start_time
            return {
                "success": False,
                "output": "",
                "error": f"Timeout after {timeout}s",
                "duration_s": duration,
                "cost_usd": None,
            }

        duration = time.monotonic() - start_time

        if proc.returncode != 0:
            return {
                "success": False,
                "output": stdout,
                "error": stderr or f"Exit code {proc.returncode}",
                "duration_s": duration,
                "cost_usd": None,
            }

        # Try to parse JSON output
        result_text = stdout.strip()
        cost_usd = None
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                result_text = parsed.get("result", result_text)
                cost_usd = parsed.get("cost_usd")
        except json.JSONDecodeError:
            pass  # Keep raw text output

        return {
            "success": True,
            "output": result_text,
            "error": None,
            "duration_s": duration,
            "cost_usd": cost_usd,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "output": "",
            "error": "claude command not found. Install Claude Code CLI: npm install -g @anthropic-ai/claude-code",
            "duration_s": 0,
            "cost_usd": None,
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "duration_s": time.monotonic() - start_time,
            "cost_usd": None,
        }
