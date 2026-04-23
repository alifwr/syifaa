import pytest
from sqlalchemy import text
from app.db import get_engine

@pytest.mark.asyncio
async def test_engine_can_connect():
    eng = get_engine()
    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
