import os
import pytest
from cryptography.fernet import Fernet
from testcontainers.postgres import PostgresContainer

# NOTE: The placeholder FERNET_KEY below is intentionally NOT a valid Fernet
# key. Tests that actually encrypt must supply their own via monkeypatch
# (see future tests for encryption + LLM gateway). Keeping a valid random key
# here would hide bugs where something silently decrypts against a rotating key.
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-xxxxxxx")
os.environ.setdefault("FERNET_KEY", "placeholder-overridden-per-test")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:3000/auth/google/callback")
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
        # Register a DDL event so every Base.metadata.create_all call first
        # ensures the pgvector extension exists, even after a DROP SCHEMA reset.
        from sqlalchemy import event, text
        from app.models.base import Base

        @event.listens_for(Base.metadata, "before_create")
        def _create_vector_extension(target, connection, **kw):
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

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


from testcontainers.localstack import LocalStackContainer


@pytest.fixture(scope="session")
def localstack():
    # .with_services must be called BEFORE __enter__ (container start) or the
    # SERVICES env var is already baked in and the call is a silent no-op.
    container = LocalStackContainer(image="localstack/localstack:3").with_services("s3")
    with container as ls:
        url = ls.get_url()
        os.environ["S3_ENDPOINT_URL"] = url
        os.environ["S3_REGION"] = "us-east-1"
        os.environ["S3_ACCESS_KEY"] = "test"
        os.environ["S3_SECRET_KEY"] = "test"
        from app.config import get_settings
        get_settings.cache_clear()
        yield url


@pytest.fixture
def s3_bucket(localstack):
    import boto3
    s = __import__("app.config", fromlist=["get_settings"]).get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
    )
    try:
        client.create_bucket(Bucket=s.s3_bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    yield s.s3_bucket
    # cleanup: empty bucket between tests so keys don't leak across cases
    objs = client.list_objects_v2(Bucket=s.s3_bucket).get("Contents", [])
    for o in objs:
        client.delete_object(Bucket=s.s3_bucket, Key=o["Key"])


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    from app.config import get_settings
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


@pytest.fixture
async def fresh_schema():
    """Drop and recreate all tables so each test starts with a clean schema."""
    from app.db import get_engine
    from app.models import Base
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
