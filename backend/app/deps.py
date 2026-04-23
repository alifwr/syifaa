import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import InvalidToken, decode_jwt


log = logging.getLogger("syifa.auth")

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _reject() -> HTTPException:
    # One uniform client-facing message across every failure path so we
    # don't leak account-existence or token-shape detail to the caller.
    return HTTPException(status_code=401, detail="Invalid token")


async def current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization:
        raise _reject()

    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _reject()
    token = parts[1].strip()
    if not token:
        raise _reject()

    try:
        payload = decode_jwt(token)
    except InvalidToken as e:
        log.warning("decode_jwt failed: %s", e)
        raise _reject()

    if payload.get("kind") != "access":
        log.warning("wrong token kind: %r", payload.get("kind"))
        raise _reject()

    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        log.warning("bad sub claim: %r", payload.get("sub"))
        raise _reject()

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        log.warning("access token for missing user %s", user_id)
        raise _reject()

    return user


CurrentUser = Annotated[User, Depends(current_user)]
