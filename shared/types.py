from enum import StrEnum


class Locale(StrEnum):
    KO = "ko"
    EN = "en"


class AgentType(StrEnum):
    CHAT = "chat"
    BRIEFING = "briefing"
    PROACTIVE = "proactive"
    TASK = "task"
    REPORT = "report"
    CLAUDE_CODE = "claude_code"
    CALENDAR = "calendar"
    MAIL = "mail"
    SEARCH = "search"
    RAG = "rag"
    SAP = "sap"


class OnboardingStage(StrEnum):
    NOT_STARTED = "not_started"
    API_KEYS = "api_keys"
    GOOGLE_AUTH = "google_auth"
    PREFERENCES = "preferences"
    COMPLETED = "completed"
