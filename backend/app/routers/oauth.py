import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import DbSession
from app.models import User, OAuthAccount
from app.schemas.auth import TokenPair
from app.security import make_jwt


router = APIRouter(prefix="/auth/google", tags=["oauth"])

GOOGLE_AUTHZ = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

STATE_COOKIE = "oauth_state"
STATE_TTL = 600  # 10 minutes


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
async def login_start(response: Response):
    s = get_settings()
    state = secrets.token_urlsafe(32)
    qs = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": s.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            # access_type=online (not offline) — we don't need a Google refresh
            # token because we don't act on behalf of the user against Google APIs.
            "access_type": "online",
            "prompt": "select_account",
            "state": state,
        }
    )
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
    )
    return {"authorization_url": f"{GOOGLE_AUTHZ}?{qs}"}


@router.get("/callback", response_model=TokenPair)
async def callback(
    code: str,
    state: str,
    db: DbSession,
    response: Response,
    oauth_state: str | None = Cookie(default=None, alias=STATE_COOKIE),
) -> TokenPair:
    if not oauth_state or not secrets.compare_digest(oauth_state, state):
        raise HTTPException(status_code=400, detail="Invalid state")

    try:
        info = await fetch_userinfo(code)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid authorization code",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail="Upstream identity provider unreachable",
        ) from e

    if not info.get("email_verified", False):
        raise HTTPException(
            status_code=400,
            detail="Google account email is not verified.",
        )

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
        try:
            await db.commit()
        except IntegrityError as e:
            # TOCTOU race with another signup or OAuth callback for the same
            # email / sub — surface as 409 rather than a 500.
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use; link Google from settings.",
            ) from e
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
    response.delete_cookie(STATE_COOKIE)
    return TokenPair(access_token=access, refresh_token=refresh)
