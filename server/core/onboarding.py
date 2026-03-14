"""Interactive onboarding wizard — guides user through setup stages."""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from server.core.auth import build_google_auth_url
from server.database import crud
from shared.types import OnboardingStage

logger = logging.getLogger(__name__)


async def get_onboarding_status(db: aiosqlite.Connection) -> dict[str, Any]:
    state = await crud.get_user_state(db)
    if not state:
        return {"stage": OnboardingStage.NOT_STARTED, "completed": False}
    return {
        "stage": state.get("onboarding_stage", OnboardingStage.NOT_STARTED),
        "completed": state.get("onboarding_stage") == OnboardingStage.COMPLETED,
        "has_google": bool(state.get("google_token")),
        "locale": state.get("locale", "ko"),
    }


async def advance_onboarding(
    db: aiosqlite.Connection,
    current_stage: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance to the next onboarding stage."""
    data = data or {}

    if current_stage == OnboardingStage.NOT_STARTED:
        await crud.upsert_user_state(db, onboarding_stage=OnboardingStage.API_KEYS)
        return {
            "stage": OnboardingStage.API_KEYS,
            "message": "API 키를 설정해 주세요. .env 파일에 ANTHROPIC_API_KEY를 입력하면 됩니다.",
            "required": ["ANTHROPIC_API_KEY"],
            "optional": ["DEEPGRAM_API_KEY"],
        }

    elif current_stage == OnboardingStage.API_KEYS:
        await crud.upsert_user_state(db, onboarding_stage=OnboardingStage.GOOGLE_AUTH)
        google_url = build_google_auth_url()
        return {
            "stage": OnboardingStage.GOOGLE_AUTH,
            "message": "Google 계정을 연동하면 Gmail, Calendar, Drive 데이터를 자동으로 수집합니다.",
            "auth_url": google_url or "Google 자격증명이 설정되지 않았습니다. 건너뛰기 가능합니다.",
            "skippable": True,
        }

    elif current_stage == OnboardingStage.GOOGLE_AUTH:
        if data.get("google_token"):
            await crud.upsert_user_state(db, google_token=data["google_token"])
        await crud.upsert_user_state(db, onboarding_stage=OnboardingStage.PREFERENCES)
        return {
            "stage": OnboardingStage.PREFERENCES,
            "message": "기본 설정을 완료해 주세요.",
            "options": {
                "locale": ["ko", "en"],
                "briefing_time": "08:00",
            },
        }

    elif current_stage == OnboardingStage.PREFERENCES:
        locale = data.get("locale", "ko")
        await crud.upsert_user_state(
            db, onboarding_stage=OnboardingStage.COMPLETED, locale=locale
        )
        return {
            "stage": OnboardingStage.COMPLETED,
            "message": "설정이 완료되었습니다! J.A.R.V.I.S가 준비되었습니다.",
            "completed": True,
        }

    return {"stage": current_stage, "message": "알 수 없는 단계입니다."}
