"""Authentication endpoints: staff self-registration, login, current-user lookup."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, UserRole
from app.schemas import Token, UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


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
    await db.commit()
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

    if (
        user is None
        or not user.is_active
        or not verify_password(form_data.password, user.hashed_password)
    ):
        raise generic_error

    access_token = create_access_token(subject=user.email)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
