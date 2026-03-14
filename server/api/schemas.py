"""Pydantic request/response schemas for the J.A.R.V.I.S API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Command ────────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    text: str = Field(..., min_length=1, description="User input text")
    locale: str = "ko"
    history: list[dict[str, str]] = Field(default_factory=list)


class CommandResponse(BaseModel):
    reply: str
    agent: str | None = None


# ── Push — Mobile activity data ────────────────────────────────────────

class AppUsageRecord(BaseModel):
    package: str
    app_name: str | None = None
    started_at: str
    ended_at: str | None = None
    duration_s: int | None = None


class CallLogRecord(BaseModel):
    phone_number: str
    direction: str = "unknown"
    started_at: str
    duration_s: float | None = None
    transcript: str | None = None


class LocationRecord(BaseModel):
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    label: str | None = None
    recorded_at: str


class PushActivityRequest(BaseModel):
    app_usage: list[AppUsageRecord] = Field(default_factory=list)
    call_logs: list[CallLogRecord] = Field(default_factory=list)
    locations: list[LocationRecord] = Field(default_factory=list)


class PushResponse(BaseModel):
    ingested: dict[str, int]


# ── Push — PC activity data ───────────────────────────────────────────

class PcActivityRecord(BaseModel):
    window_title: str
    process_name: str | None = None
    url: str | None = None
    started_at: str
    ended_at: str | None = None
    duration_s: int | None = None
    idle: bool = False


class PushPcActivityRequest(BaseModel):
    activities: list[PcActivityRecord]


# ── Tasks ──────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: str | None = None
    due_date: str | None = None
    priority: str = "normal"


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    priority: str | None = None
    status: str | None = None


# ── Briefing ───────────────────────────────────────────────────────────

class BriefingRequest(BaseModel):
    type: str = "morning"
    locale: str = "ko"


class BriefingResponse(BaseModel):
    type: str
    content: str
    date: str


# ── Data query ─────────────────────────────────────────────────────────

class ActivityQuery(BaseModel):
    date: str | None = None
    since: str | None = None
    until: str | None = None
    device: str | None = None
    limit: int = 100


# ── Screen text ───────────────────────────────────────────────────────

class ScreenTextRecord(BaseModel):
    app_name: str | None = None
    window_title: str | None = None
    extracted_text: str
    text_length: int | None = None
    timestamp: str


class PushScreenTextRequest(BaseModel):
    records: list[ScreenTextRecord]


# ── Onboarding ─────────────────────────────────────────────────────────

class OnboardingAdvance(BaseModel):
    stage: str
    data: dict | None = None
