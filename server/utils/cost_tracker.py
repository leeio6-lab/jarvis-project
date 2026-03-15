"""Tracks API call costs (Anthropic, OpenAI) per session/day.

Pricing (as of 2025-05):
  gpt-4.1-nano:    $0.10 / 1M input, $0.40 / 1M output
  gpt-4.1-mini:    $0.40 / 1M input, $1.60 / 1M output
  claude-sonnet-4: $3.00 / 1M input, $15.00 / 1M output
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (USD)
PRICING = {
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    # Fallback for unknown models
    "_default": {"input": 1.00, "output": 4.00},
}


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    purpose: str
    timestamp: str


@dataclass
class CostTracker:
    """Singleton-style cost tracker — accumulates costs across the session."""

    calls: list[CallRecord] = field(default_factory=list)
    _by_model: dict[str, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: {"input": 0, "output": 0, "cost": 0.0, "count": 0})
    )
    _by_purpose: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    session_start: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def record(
        self,
        model: str,
        usage: dict[str, Any] | None,
        latency_ms: int = 0,
        purpose: str = "",
    ) -> float:
        """Record an API call and return its cost in USD."""
        if not usage:
            return 0.0

        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens", 0)
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens", 0)

        pricing = PRICING.get(model, PRICING["_default"])
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        record = CallRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=latency_ms,
            purpose=purpose,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.calls.append(record)

        self._by_model[model]["input"] += input_tokens
        self._by_model[model]["output"] += output_tokens
        self._by_model[model]["cost"] += cost
        self._by_model[model]["count"] += 1
        self._by_purpose[purpose or "unknown"] += cost

        return cost

    @property
    def total_cost(self) -> float:
        return sum(m["cost"] for m in self._by_model.values())

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(m["input"] for m in self._by_model.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(m["output"] for m in self._by_model.values())

    def summary(self) -> dict[str, Any]:
        """Full cost summary for reporting."""
        return {
            "session_start": self.session_start,
            "total_calls": self.total_calls,
            "total_cost_usd": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "by_model": {
                model: {
                    "calls": int(data["count"]),
                    "input_tokens": int(data["input"]),
                    "output_tokens": int(data["output"]),
                    "cost_usd": round(data["cost"], 4),
                }
                for model, data in self._by_model.items()
            },
            "by_purpose": {k: round(v, 4) for k, v in self._by_purpose.items()},
            "monthly_estimate_usd": round(self._estimate_monthly(), 2),
            "daily_estimate_usd": round(self._estimate_daily(), 4),
        }

    def _estimate_daily(self) -> float:
        """Estimate daily cost based on current usage rate."""
        if not self.calls:
            return 0.0
        first = self.calls[0].timestamp
        last = self.calls[-1].timestamp
        try:
            elapsed_h = (
                datetime.fromisoformat(last) - datetime.fromisoformat(first)
            ).total_seconds() / 3600
        except (ValueError, TypeError):
            elapsed_h = 1.0
        if elapsed_h < 0.1:
            elapsed_h = 0.5  # minimum half hour
        hourly_rate = self.total_cost / elapsed_h
        return hourly_rate * 8  # 8 working hours

    def _estimate_monthly(self) -> float:
        """Estimate monthly cost: daily * 22 working days."""
        return self._estimate_daily() * 22


# Global singleton
tracker = CostTracker()
