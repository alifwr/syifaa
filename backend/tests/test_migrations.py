import pytest
from sqlalchemy import text
from app.db import get_engine

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
