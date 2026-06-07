from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_service_key: str
    supabase_jwt_secret: str

    # Database (asyncpg connection string)
    database_url: str

    # OpenAI
    openai_api_key: str

    # Resend
    resend_api_key: str

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Scheduler toggles (disable in tests)
    scheduler_enabled: bool = True

    @property
    def database_url_sync(self) -> str:
        """Derive a sync-friendly connection string from the async URL.
        PGVector (langchain-postgres) calls synchronous DB operations
        internally, so it needs a sync driver (psycopg2) instead of asyncpg."""
        return self.database_url.replace("+asyncpg", "+psycopg2")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
