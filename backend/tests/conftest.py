import os
import pytest
from testcontainers.postgres import PostgresContainer

# NOTE: The placeholder FERNET_KEY below is intentionally NOT a valid Fernet
# key. Tests that actually encrypt must supply their own via monkeypatch
# (see future tests for encryption + LLM gateway). Keeping a valid random key
# here would hide bugs where something silently decrypts against a rotating key.
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-xxxxxxx")
os.environ.setdefault("FERNET_KEY", "placeholder-overridden-per-test")
# DATABASE_URL placeholder satisfies Settings validation at import/collection time;
# the pg_url fixture overwrites it (and clears the lru_cache) before any test runs.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        raw = pg.get_connection_url()                     # postgresql+psycopg2://...
        url = raw.replace("+psycopg2", "+asyncpg")
        os.environ["DATABASE_URL"] = url
        # Invalidate any cached Settings snapshot so tests see the container URL.
        from app.config import get_settings
        get_settings.cache_clear()
        yield url

@pytest.fixture(autouse=True)
def _require_pg(pg_url):
    # Every test gets DATABASE_URL pointing at the container.
    yield

@pytest.fixture(autouse=True)
async def _reset_engine_per_test():
    yield
    from app.db import dispose_engine
    await dispose_engine()
