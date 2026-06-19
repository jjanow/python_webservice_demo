"""Password hashing (bcrypt direct) and JWT helpers (PyJWT direct).

We avoid passlib (incompatible with bcrypt>=4.1) and python-jose (unmaintained,
history of algorithm-confusion CVEs) by calling bcrypt and PyJWT directly.
"""
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt, returning a utf-8 string for storage."""
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Create a signed JWT access token. `subject` is typically the user's email."""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, raising jwt.PyJWTError subclasses on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
