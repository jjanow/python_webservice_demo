"""Authentication endpoints: staff self-registration, login, current-user lookup."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, UserRole
from app.schemas import Token, UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

# Pre-computed bcrypt hash of a random value. When login is attempted for a
# missing/inactive account we still run a verify against this so that the
# response time is the same as for an existing account with a wrong password,
# closing the timing side-channel that would otherwise enumerate valid emails.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request, payload: UserCreate, db: AsyncSession = Depends(get_db)
) -> User:
    """Create a staff account. Role is always forced to STAFF server-side."""
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.STAFF,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race against a concurrent registration with the same email; the
        # unique constraint is the real guard, so surface it as a clean 409.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """OAuth2 password flow login. Rate-limited to mitigate brute force."""
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None or not user.is_active:
        # Run a verify against a dummy hash anyway so a missing/inactive account
        # costs the same wall-clock time as a real one with a wrong password,
        # preventing timing-based user enumeration.
        verify_password(form_data.password, _DUMMY_PASSWORD_HASH)
        raise generic_error

    if not verify_password(form_data.password, user.hashed_password):
        raise generic_error

    access_token = create_access_token(subject=user.email)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
