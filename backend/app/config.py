from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Local dev defaults to SQLite so the app runs with zero infrastructure.
    # Production sets DATABASE_URL to a Neon Postgres URL (postgresql+asyncpg://...).
    database_url: str = "sqlite+aiosqlite:///./parlay.db"

    # Signs our own session JWT. MUST be overridden in production.
    # At least 32 bytes so PyJWT does not warn about a weak HMAC key.
    session_secret: str = "dev-insecure-secret-change-me-before-deploying-anywhere"
    session_ttl_days: int = 30

    # Google Identity Services client ID (also used as the ID token audience).
    google_client_id: str = ""

    frontend_origin: str = "http://localhost:5173"
    # Base URL used in notification links. Defaults to the first allowed origin.
    app_url: str = ""
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None

    # Shared secret guarding POST /internal/tick. Never exposed to the browser.
    internal_tick_secret: str = "dev-tick-secret"

    resend_api_key: str = ""
    email_from: str = "Parlay <onboarding@resend.dev>"

    sleeper_base_url: str = "https://api.sleeper.app/v1"
    espn_base_url: str = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
    http_timeout_seconds: float = 15.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def public_app_url(self) -> str:
        return self.app_url or (self.allowed_origins[0] if self.allowed_origins else "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
