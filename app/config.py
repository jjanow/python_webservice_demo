"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"", "change-me-to-a-long-random-string", "changeme", "secret"}
# Known-weak/default admin passwords that must never reach a production deploy.
_PLACEHOLDER_ADMIN_PASSWORDS = {"", "admin", "change-me-too", "changeme", "password"}
_MIN_ADMIN_PASSWORD_LENGTH = 8


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
        """Fail fast rather than start a production deployment with insecure config.

        Covers both the JWT signing key and the seeded admin password: a strong
        SECRET_KEY is useless if the privileged admin account ships with the
        default `admin` password, so both are gated on ENVIRONMENT=production.
        """
        if self.ENVIRONMENT != "production":
            return

        if self.SECRET_KEY.strip() in _PLACEHOLDER_SECRETS:
            raise RuntimeError(
                "SECRET_KEY is empty or a known placeholder while ENVIRONMENT=production. "
                "Set a long, random SECRET_KEY before starting in production."
            )

        if (
            self.ADMIN_PASSWORD.strip() in _PLACEHOLDER_ADMIN_PASSWORDS
            or len(self.ADMIN_PASSWORD) < _MIN_ADMIN_PASSWORD_LENGTH
        ):
            raise RuntimeError(
                "ADMIN_PASSWORD is empty, a known placeholder, or shorter than "
                f"{_MIN_ADMIN_PASSWORD_LENGTH} characters while ENVIRONMENT=production. "
                "Set a strong ADMIN_PASSWORD before starting in production."
            )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton; lru_cache means the .env file is read only once."""
    return Settings()


settings = get_settings()
settings.validate_production_secret()
