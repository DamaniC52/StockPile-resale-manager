"""Signup, login, and current-user routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.ratelimit import rate_limit_auth
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
)
def signup(payload: UserCreate, db: DbSession) -> User:
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The unique index on lower(email) is the real guard. Checking first and
        # inserting after would leave a race window between the two statements.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    db.refresh(user)
    return user


@router.post("/login", response_model=Token, dependencies=[Depends(rate_limit_auth)])
def login(payload: UserLogin, db: DbSession) -> Token:
    user = db.scalar(
        select(User).where(func.lower(User.email) == payload.email.lower())
    )

    # Always run the hash comparison, even for an unknown email. Skipping it
    # would make unknown emails answer in ~1ms and known ones in ~250ms, letting
    # an attacker enumerate registered accounts by timing alone.
    stored_hash = user.hashed_password if user is not None else DUMMY_HASH
    password_ok = verify_password(payload.password, stored_hash)

    if user is None or not password_ok or not user.is_active:
        # One code and one message for every failure mode, so the response
        # reveals nothing about which accounts exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserRead)
def read_current_user(user: CurrentUser) -> User:
    return user
