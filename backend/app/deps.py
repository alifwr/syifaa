from typing import Annotated
from uuid import UUID
from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import User
from app.security import InvalidToken, decode_jwt


DbSession = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
    except InvalidToken:
        # Do NOT echo the underlying PyJWT message — treat all failure modes uniformly.
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("kind") != "access":
        raise HTTPException(status_code=401, detail="Wrong token kind")
    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
