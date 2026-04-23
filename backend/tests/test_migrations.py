import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.config import get_settings
from app.db import dispose_engine, get_engine


@pytest.mark.asyncio
async def test_core_tables_exist_after_create_all():
    # Test-level schema init: use create_all from the models' metadata.
    # (Alembic migrations are verified manually — see plan task 4, step 9.)
    from app.models import Base
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with eng.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))).all()
        names = {r[0] for r in rows}
    assert {"user", "oauth_account", "llm_config"}.issubset(names)


@pytest.mark.asyncio
async def test_alembic_upgrade_head_applies_initial_schema():
    """Run the real Alembic migration against a clean schema, not just create_all."""
    # Drop everything so the migration applies from scratch.
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await dispose_engine()

    cfg = Config("/home/seratusjuta/syifa/backend/alembic.ini")
    # env.py pulls DATABASE_URL from get_settings; it's already set by the
    # pg_url fixture.
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)

    # alembic.command.upgrade is sync and internally runs asyncio.run.
    # We can't call it from inside our async test (running loop conflict).
    # Run it in a subprocess-style thread executor.
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: command.upgrade(cfg, "head"))

    eng2 = get_engine()
    async with eng2.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))).all()
        names = {r[0] for r in rows}
    assert {"alembic_version", "user", "oauth_account", "llm_config"}.issubset(names)
