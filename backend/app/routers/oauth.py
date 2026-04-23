from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DbSession
from app.models import User, OAuthAccount
from app.schemas.auth import TokenPair
from app.security import make_jwt


router = APIRouter(prefix="/auth/google", tags=["oauth"])

GOOGLE_AUTHZ = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


async def fetch_userinfo(code: str) -> dict:
    """Exchange authorization code for userinfo.

    Overridden in tests via monkeypatch to avoid real Google traffic.
    """
    s = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as h:
        tok = await h.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        tok.raise_for_status()
        access = tok.json()["access_token"]
        info = await h.get(
            GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"}
        )
        info.raise_for_status()
        return info.json()


@router.get("/login")
async def login_start():
    s = get_settings()
    qs = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": s.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return {"authorization_url": f"{GOOGLE_AUTHZ}?{qs}"}


@router.get("/callback", response_model=TokenPair)
async def callback(code: str, db: DbSession) -> TokenPair:
    info = await fetch_userinfo(code)
    sub = info["sub"]
    email = info["email"]

    oa = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == "google",
                OAuthAccount.provider_sub == sub,
            )
        )
    ).scalar_one_or_none()

    if oa is not None:
        user_id = oa.user_id
    else:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            # Same email but different (or no) Google sub — require explicit
            # account linking from settings instead of silently merging.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use; link Google from settings.",
            )
        user = User(email=email, pw_hash=None)
        db.add(user)
        await db.flush()
        db.add(
            OAuthAccount(
                user_id=user.id,
                provider="google",
                provider_sub=sub,
                email=email,
            )
        )
        await db.commit()
        user_id = user.id

    s = get_settings()
    access = make_jwt(
        {"sub": str(user_id), "kind": "access"},
        timedelta(minutes=s.jwt_access_ttl_min),
    )
    refresh = make_jwt(
        {"sub": str(user_id), "kind": "refresh"},
        timedelta(days=s.jwt_refresh_ttl_days),
    )
    return TokenPair(access_token=access, refresh_token=refresh)
