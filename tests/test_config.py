"""Production config fail-fast: SECRET_KEY and ADMIN_PASSWORD must be strong."""
import pytest

from app.config import Settings

_STRONG_SECRET = "a-very-long-random-secret-value-0123456789-abcdef"
_STRONG_ADMIN_PASSWORD = "a-strong-admin-password"


def test_production_rejects_placeholder_secret():
    settings = Settings(
        SECRET_KEY="change-me-to-a-long-random-string",
        ENVIRONMENT="production",
        ADMIN_PASSWORD=_STRONG_ADMIN_PASSWORD,
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.validate_production_secret()


def test_production_rejects_default_admin_password():
    settings = Settings(
        SECRET_KEY=_STRONG_SECRET,
        ENVIRONMENT="production",
        ADMIN_PASSWORD="admin",
    )
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        settings.validate_production_secret()


def test_production_rejects_short_admin_password():
    settings = Settings(
        SECRET_KEY=_STRONG_SECRET,
        ENVIRONMENT="production",
        ADMIN_PASSWORD="short1",
    )
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        settings.validate_production_secret()


def test_production_accepts_strong_config():
    settings = Settings(
        SECRET_KEY=_STRONG_SECRET,
        ENVIRONMENT="production",
        ADMIN_PASSWORD=_STRONG_ADMIN_PASSWORD,
    )
    settings.validate_production_secret()


def test_non_production_skips_validation():
    # Weak values are tolerated outside production (e.g. local dev/tests).
    settings = Settings(SECRET_KEY="", ENVIRONMENT="development", ADMIN_PASSWORD="admin")
    settings.validate_production_secret()
