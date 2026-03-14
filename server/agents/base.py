"""Abstract base class for all J.A.R.V.I.S agents + unified LLM caller.

Supports both OpenAI (gpt-*) and Anthropic (claude-*) models.
Routes automatically based on model prefix.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from server.config.settings import settings

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


# ── Unified LLM caller ────────────────────────────────────────────────

async def call_llm(
    messages: list[dict[str, Any]],
    *,
    tier: str = "medium",
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Call LLM with automatic provider routing.

    tier: "light" | "medium" | "heavy" — maps to model via settings.
    model: override tier with explicit model name.

    Returns normalized response: {content: [{type: "text", text: "..."}], ...}
    """
    resolved_model = model or settings.get_model(tier)

    if settings.is_openai_model(resolved_model):
        return await _call_openai(messages, system=system, tools=tools,
                                  model=resolved_model, max_tokens=max_tokens)
    else:
        return await _call_anthropic(messages, system=system, tools=tools,
                                     model=resolved_model, max_tokens=max_tokens)


# ── Backward-compatible alias ──────────────────────────────────────────

async def call_claude(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Backward-compatible: routes through call_llm with medium tier."""
    return await call_llm(messages, system=system, tools=tools,
                          model=model, max_tokens=max_tokens)


# ── Anthropic provider ────────────────────────────────────────────────

async def _call_anthropic(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if not settings.has_anthropic:
        return _mock_response(messages, model)

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens or 4096,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()


# ── OpenAI provider ───────────────────────────────────────────────────

async def _call_openai(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if not settings.has_openai:
        # Fallback: try Anthropic with default model if available
        if settings.has_anthropic:
            logger.info("OpenAI key missing, falling back to Anthropic")
            return await _call_anthropic(
                messages, system=system, tools=tools,
                model=settings.llm_tier_heavy, max_tokens=max_tokens,
            )
        return _mock_response(messages, model)

    # Build OpenAI messages (system goes as first message)
    oai_messages = []
    if system:
        oai_messages.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        # Normalize Anthropic tool_result format to OpenAI
        if isinstance(content, list):
            # Anthropic tool results → flatten to text for OpenAI
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        parts.append(block.get("content", ""))
                    elif block.get("type") == "text":
                        parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            content = "\n".join(parts)
        oai_messages.append({"role": role, "content": content})

    payload: dict[str, Any] = {
        "model": model,
        "messages": oai_messages,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    # Convert Anthropic tool format to OpenAI function format
    if tools:
        oai_tools = []
        for t in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            })
        payload["tools"] = oai_tools

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _OPENAI_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        oai_resp = resp.json()

    # Normalize OpenAI response to Anthropic format for compatibility
    return _normalize_openai_response(oai_resp, model)


def _normalize_openai_response(oai_resp: dict, model: str) -> dict[str, Any]:
    """Convert OpenAI response to Anthropic-compatible format."""
    choice = oai_resp.get("choices", [{}])[0]
    msg = choice.get("message", {})

    content_blocks: list[dict[str, Any]] = []

    # Text content
    if msg.get("content"):
        content_blocks.append({"type": "text", "text": msg["content"]})

    # Tool calls
    for tc in msg.get("tool_calls", []):
        import json
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": tc["function"]["name"],
            "input": json.loads(tc["function"].get("arguments", "{}")),
        })

    return {
        "id": oai_resp.get("id", ""),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": "end_turn" if choice.get("finish_reason") == "stop" else choice.get("finish_reason"),
        "usage": oai_resp.get("usage"),
    }


# ── Mock response ─────────────────────────────────────────────────────

def _mock_response(messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
    logger.warning("No API key configured for %s - returning mock", model)
    user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            user_text = content if isinstance(content, str) else str(content)
            break
    return {
        "id": "mock_msg",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": f"[MOCK] API key missing ({model}). Input: {user_text[:100]}"}],
        "model": model,
        "stop_reason": "end_turn",
    }


# ── Response helpers ───────────────────────────────────────────────────

def extract_text(response: dict[str, Any]) -> str:
    """Extract text content from a normalized LLM response."""
    parts = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts)


def extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool_use blocks from a normalized LLM response."""
    return [
        block for block in response.get("content", [])
        if block.get("type") == "tool_use"
    ]


class BaseAgent(ABC):
    name: str = "base"

    @abstractmethod
    async def run(self, user_input: str, context: dict[str, Any]) -> str:
        ...
