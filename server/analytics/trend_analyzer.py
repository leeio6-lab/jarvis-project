"""Weekly/monthly trend analysis across all crawled data sources.

Tracks changes over time:
- App usage patterns (which apps increased/decreased)
- Productivity score trends
- Promise fulfillment rate
- Work/leisure balance shifts
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from server.analytics.activity_analyzer import format_duration, get_daily_summary
from server.analytics.productivity_score import calculate_daily_score
from server.database import crud

logger = logging.getLogger(__name__)


async def weekly_trend(
    db: aiosqlite.Connection,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Generate weekly trend analysis.

    Compares this week vs last week across all metrics.
    """
    if end_date:
        end = datetime.fromisoformat(end_date)
    else:
        end = datetime.now(timezone.utc)

    # This week (last 7 days)
    this_week = []
    for i in range(7):
        day = (end - timedelta(days=i)).strftime("%Y-%m-%d")
        summary = await get_daily_summary(db, date=day)
        score = await calculate_daily_score(db, date=day)
        this_week.append({
            "date": day,
            "total_active_s": summary["total_active_s"],
            "mobile_s": summary["mobile"]["total_s"],
            "pc_s": summary["pc"]["total_s"],
            "score": score["score"],
        })
    this_week.reverse()

    # Last week (7-14 days ago)
    last_week = []
    for i in range(7, 14):
        day = (end - timedelta(days=i)).strftime("%Y-%m-%d")
        summary = await get_daily_summary(db, date=day)
        score = await calculate_daily_score(db, date=day)
        last_week.append({
            "date": day,
            "total_active_s": summary["total_active_s"],
            "mobile_s": summary["mobile"]["total_s"],
            "pc_s": summary["pc"]["total_s"],
            "score": score["score"],
        })
    last_week.reverse()

    # Aggregates
    tw_active = sum(d["total_active_s"] for d in this_week)
    lw_active = sum(d["total_active_s"] for d in last_week)
    tw_score = sum(d["score"] for d in this_week) / max(len(this_week), 1)
    lw_score = sum(d["score"] for d in last_week) / max(len(last_week), 1)
    tw_mobile = sum(d["mobile_s"] for d in this_week)
    tw_pc = sum(d["pc_s"] for d in this_week)

    # Top apps this week
    week_start = (end - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
    week_end = end.strftime("%Y-%m-%dT23:59:59")
    top_mobile = await crud.get_app_usage_summary(
        db, since=week_start, until=week_end, device="mobile"
    )
    top_pc = await crud.get_pc_activity_summary(db, since=week_start, until=week_end)

    # Promise stats
    pending = await crud.get_promises(db, status="pending")
    done = await crud.get_promises(db, status="done")
    overdue = await crud.get_promises(db, status="overdue")

    return {
        "period": f"{this_week[0]['date']} ~ {this_week[-1]['date']}" if this_week else "",
        "daily_breakdown": this_week,
        "comparison": {
            "total_active": {
                "this_week": tw_active,
                "last_week": lw_active,
                "change_pct": _pct_change(lw_active, tw_active),
                "this_week_formatted": format_duration(tw_active),
                "last_week_formatted": format_duration(lw_active),
            },
            "avg_score": {
                "this_week": round(tw_score, 1),
                "last_week": round(lw_score, 1),
                "change": round(tw_score - lw_score, 1),
            },
            "mobile_vs_pc": {
                "mobile_s": tw_mobile,
                "pc_s": tw_pc,
                "mobile_pct": round(tw_mobile / max(tw_active, 1) * 100, 1),
                "pc_pct": round(tw_pc / max(tw_active, 1) * 100, 1),
            },
        },
        "top_apps": {
            "mobile": top_mobile[:5],
            "pc": top_pc[:5],
        },
        "promises": {
            "pending": len(pending),
            "done": len(done),
            "overdue": len(overdue),
            "rate": round(len(done) / max(len(done) + len(overdue), 1) * 100, 1),
        },
    }


async def monthly_trend(
    db: aiosqlite.Connection,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Generate monthly trend — weekly aggregates for 4 weeks."""
    if end_date:
        end = datetime.fromisoformat(end_date)
    else:
        end = datetime.now(timezone.utc)

    weeks = []
    for w in range(4):
        week_end = (end - timedelta(weeks=w)).strftime("%Y-%m-%d")
        trend = await weekly_trend(db, end_date=week_end)
        weeks.append({
            "week": w + 1,
            "period": trend["period"],
            "total_active_s": trend["comparison"]["total_active"]["this_week"],
            "avg_score": trend["comparison"]["avg_score"]["this_week"],
        })

    weeks.reverse()

    # Score trend direction
    if len(weeks) >= 2:
        recent = weeks[-1]["avg_score"]
        older = weeks[0]["avg_score"]
        trend_direction = "up" if recent > older else ("down" if recent < older else "stable")
    else:
        trend_direction = "stable"

    return {
        "weeks": weeks,
        "trend_direction": trend_direction,
    }


def _pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 1)
