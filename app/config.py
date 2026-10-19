from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase project the users' access tokens come from. The service reads
    # training data with the caller's own token, so Row Level Security decides
    # what it can see; no service-role key is ever configured here.
    supabase_url: str
    supabase_anon_key: str

    # Without a key the service runs the free rule-based coach only. With one,
    # Claude writes the reports and the rule-based coach covers its failures.
    anthropic_api_key: str | None = None
    coach_model: str = "claude-opus-5-5"
    coach_effort: str = "low"

    # How much history the statistics look at.
    history_weeks: int = 8

    # Reports are cached per user and per data snapshot, so a refresh with no
    # new training costs nothing.
    cache_ttl_seconds: int = 6 * 60 * 60

    # Comma-separated origins allowed to call the API from a browser.
    cors_origins: str = "https://forgerep.app,http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
