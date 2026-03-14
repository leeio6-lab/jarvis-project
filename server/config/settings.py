from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "J.A.R.V.I.S"
    app_env: str = "development"
    app_port: int = 8000
    app_locale: str = "ko"

    # LLM Tiers — cost optimization
    llm_tier_light: str = "gpt-4.1-nano"       # cheap: screen summary, promise extraction, alerts
    llm_tier_medium: str = "gpt-4.1-mini"       # moderate: chat, briefing, orchestrator
    llm_tier_heavy: str = "claude-sonnet-4-20250514"  # expensive: complex analysis (user-selected)

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Deepgram
    deepgram_api_key: str = ""

    # Google
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Database
    database_url: str = "sqlite+aiosqlite:///./jarvis.db"

    # JWT
    jwt_secret_key: str = "jarvis-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    def get_model(self, tier: str = "medium") -> str:
        return {
            "light": self.llm_tier_light,
            "medium": self.llm_tier_medium,
            "heavy": self.llm_tier_heavy,
        }.get(tier, self.llm_tier_medium)

    def is_openai_model(self, model: str) -> bool:
        return model.startswith(("gpt-", "o1", "o3", "o4"))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key != "sk-ant-xxx")

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key != "sk-xxx")

    @property
    def has_deepgram(self) -> bool:
        return bool(self.deepgram_api_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()
