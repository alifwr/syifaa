from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)
from app.config import get_settings

_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None

def get_engine() -> AsyncEngine:
    global _engine, _maker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.database_url, pool_pre_ping=True)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    if _maker is None:
        raise RuntimeError("sessionmaker not initialized")
    return _maker

async def dispose_engine() -> None:
    """Close the engine's pool. Call from FastAPI lifespan shutdown."""
    global _engine, _maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _maker = None

async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as sess:
        try:
            yield sess
        except Exception:
            await sess.rollback()
            raise
