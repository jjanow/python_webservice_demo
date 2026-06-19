"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"", "change-me-to-a-long-random-string", "changeme", "secret"}


class Settings(BaseSettings):
    """Centralized app settings, populated from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"

    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "admin"

    CORS_ORIGINS: str = ""

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS_ORIGINS string into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def validate_production_secret(self) -> None:
        """Fail fast rather than start a production deployment with an insecure key."""
        if self.ENVIRONMENT == "production" and self.SECRET_KEY.strip() in _PLACEHOLDER_SECRETS:
            raise RuntimeError(
                "SECRET_KEY is empty or a known placeholder while ENVIRONMENT=production. "
                "Set a long, random SECRET_KEY before starting in production."
            )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton; lru_cache means the .env file is read only once."""
    return Settings()


settings = get_settings()
settings.validate_production_secret()
