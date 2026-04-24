import asyncio
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.db import dispose_engine, get_engine, get_sessionmaker
from app.models import User, LLMConfig


@pytest.fixture(autouse=True)
async def _schema():
    """Drop/recreate schema via Alembic upgrade head before each test."""
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await dispose_engine()

    cfg = Config("/home/seratusjuta/syifa/backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: command.upgrade(cfg, "head"))


def _mk_cfg(user_id, name, active: bool) -> LLMConfig:
    return LLMConfig(
        user_id=user_id,
        name=name,
        chat_base_url="http://x/v1",
        chat_api_key_enc="x",
        chat_model="m",
        embed_base_url="http://x/v1",
        embed_api_key_enc="x",
        embed_model="m",
        embed_dim=1536,
        is_active=active,
    )


async def test_cannot_have_two_active_configs_for_one_user():
    maker = get_sessionmaker()
    async with maker() as db:
        u = User(email="a@b.c", pw_hash="x")
        db.add(u)
        await db.commit()
        db.add(_mk_cfg(u.id, "one", True))
        await db.commit()
        db.add(_mk_cfg(u.id, "two", True))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_two_inactive_configs_are_fine():
    maker = get_sessionmaker()
    async with maker() as db:
        u = User(email="b@b.c", pw_hash="x")
        db.add(u)
        await db.commit()
        db.add(_mk_cfg(u.id, "one", False))
        db.add(_mk_cfg(u.id, "two", False))
        await db.commit()


async def test_two_users_can_each_have_an_active_config():
    maker = get_sessionmaker()
    async with maker() as db:
        u1 = User(email="c@b.c", pw_hash="x")
        u2 = User(email="d@b.c", pw_hash="x")
        db.add_all([u1, u2])
        await db.commit()
        db.add(_mk_cfg(u1.id, "one", True))
        db.add(_mk_cfg(u2.id, "one", True))
        await db.commit()
