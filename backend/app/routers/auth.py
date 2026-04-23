from datetime import timedelta
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import DbSession
from app.models import User
from app.schemas.auth import SignupIn, LoginIn, UserOut, TokenPair, RefreshIn
from app.security import (
    InvalidToken,
    decode_jwt,
    hash_password,
    make_jwt,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_pair(user_id: str) -> TokenPair:
    s = get_settings()
    access = make_jwt(
        {"sub": user_id, "kind": "access"},
        timedelta(minutes=s.jwt_access_ttl_min),
    )
    refresh = make_jwt(
        {"sub": user_id, "kind": "refresh"},
        timedelta(days=s.jwt_refresh_ttl_days),
    )
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupIn, db: DbSession) -> UserOut:
    user = User(email=data.email, pw_hash=hash_password(data.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)
    return UserOut(id=user.id, email=user.email)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginIn, db: DbSession) -> TokenPair:
    row = (
        await db.execute(select(User).where(User.email == data.email))
    ).scalar_one_or_none()
    if row is None or row.pw_hash is None or not verify_password(data.password, row.pw_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _issue_pair(str(row.id))


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshIn) -> TokenPair:
    try:
        payload = decode_jwt(data.refresh_token)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("kind") != "refresh":
        raise HTTPException(status_code=401, detail="Wrong token kind")
    return _issue_pair(payload["sub"])
