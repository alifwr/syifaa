import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine

@pytest.fixture
async def client():
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def test_signup_creates_user(client):
    r = await client.post("/auth/signup", json={
        "email": "a@b.com", "password": "correct horse battery staple",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "a@b.com"
    assert "id" in body
    assert "password" not in body and "pw_hash" not in body

async def test_signup_duplicate_email_returns_409(client):
    payload = {"email": "dup@b.com", "password": "pw_long_enough_xx"}
    await client.post("/auth/signup", json=payload)
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 409

async def test_signup_short_password_rejected(client):
    r = await client.post("/auth/signup", json={"email": "x@y.com", "password": "short"})
    assert r.status_code == 422

async def test_login_success_returns_tokens(client):
    await client.post("/auth/signup", json={"email": "l@b.com", "password": "pw_long_enough_xx"})
    r = await client.post("/auth/login", json={"email": "l@b.com", "password": "pw_long_enough_xx"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and "refresh_token" in body
    assert body["token_type"] == "bearer"

async def test_login_wrong_password_returns_401(client):
    await client.post("/auth/signup", json={"email": "w@b.com", "password": "pw_long_enough_xx"})
    r = await client.post("/auth/login", json={"email": "w@b.com", "password": "wrong_password_xx"})
    assert r.status_code == 401


async def test_login_unknown_email_returns_401(client):
    r = await client.post("/auth/login", json={"email": "nobody@b.com", "password": "doesnt_matter_xx"})
    assert r.status_code == 401
