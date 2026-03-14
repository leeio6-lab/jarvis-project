"""Agent registry - maps AgentType to agent instances."""

from __future__ import annotations

from server.agents.base import BaseAgent
from server.agents.briefing import BriefingAgent
from server.agents.chat import ChatAgent
from server.agents.claude_code import ClaudeCodeAgent
from server.agents.proactive import ProactiveAgent
from server.agents.report import ReportAgent
from server.agents.task import TaskAgent
from shared.types import AgentType

_AGENTS: dict[str, BaseAgent] = {}


def _init_agents() -> None:
    global _AGENTS
    _AGENTS = {
        AgentType.CHAT: ChatAgent(),
        AgentType.BRIEFING: BriefingAgent(),
        AgentType.TASK: TaskAgent(),
        AgentType.PROACTIVE: ProactiveAgent(),
        AgentType.CLAUDE_CODE: ClaudeCodeAgent(),
        AgentType.REPORT: ReportAgent(),
    }


def get_agent(agent_type: str) -> BaseAgent | None:
    if not _AGENTS:
        _init_agents()
    return _AGENTS.get(agent_type)


def list_agents() -> list[str]:
    if not _AGENTS:
        _init_agents()
    return list(_AGENTS.keys())
