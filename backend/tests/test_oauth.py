import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine
from app.routers import oauth as oauth_mod


@pytest.fixture
async def client(monkeypatch):
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_google_login_returns_authorization_url(client):
    r = await client.get("/auth/google/login")
    assert r.status_code == 200
    body = r.json()
    assert "authorization_url" in body
    url = body["authorization_url"]
    assert "accounts.google.com" in url
    assert "client_id=" in url
    # state param must be present in the URL
    assert "state=" in url
    # oauth_state cookie must be set
    assert "oauth_state" in r.cookies


async def test_google_login_sets_state_cookie(client):
    r = await client.get("/auth/google/login")
    assert r.status_code == 200
    # cookie present in Set-Cookie headers
    raw_setcookie = r.headers.get_list("set-cookie")
    assert any("oauth_state=" in sc.lower() for sc in raw_setcookie)
    # state also in authorization_url
    url = r.json()["authorization_url"]
    assert "state=" in url


async def test_google_callback_creates_user_and_issues_tokens(client, monkeypatch):
    async def fake(code: str):
        assert code == "FAKE-CODE"
        return {"sub": "google-sub-1", "email": "g@b.com", "email_verified": True}

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)

    client.cookies.set("oauth_state", "fake-state")
    r = await client.get(
        "/auth/google/callback",
        params={"code": "FAKE-CODE", "state": "fake-state"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_google_callback_reuses_existing_oauth_link(client, monkeypatch):
    async def fake(code: str):
        return {"sub": "google-sub-2", "email": "g2@b.com", "email_verified": True}

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)
    client.cookies.set("oauth_state", "fake-state")
    r1 = await client.get("/auth/google/callback", params={"code": "C1", "state": "fake-state"})
    r2 = await client.get("/auth/google/callback", params={"code": "C2", "state": "fake-state"})
    assert r1.status_code == 200 and r2.status_code == 200


async def test_google_callback_rejects_sub_mismatch_same_email(client, monkeypatch):
    async def fake_a(code: str):
        return {"sub": "sub-A", "email": "shared@b.com", "email_verified": True}

    async def fake_b(code: str):
        return {"sub": "sub-B", "email": "shared@b.com", "email_verified": True}

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake_a)
    client.cookies.set("oauth_state", "fake-state")
    r1 = await client.get("/auth/google/callback", params={"code": "X", "state": "fake-state"})
    assert r1.status_code == 200

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake_b)
    client.cookies.set("oauth_state", "fake-state")
    r2 = await client.get("/auth/google/callback", params={"code": "Y", "state": "fake-state"})
    assert r2.status_code == 409


async def test_google_callback_rejects_unverified_email(client, monkeypatch):
    async def fake(code: str):
        return {"sub": "sub-u", "email": "unv@b.com", "email_verified": False}

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)
    client.cookies.set("oauth_state", "fake-state")
    r = await client.get("/auth/google/callback", params={"code": "X", "state": "fake-state"})
    assert r.status_code == 400


async def test_google_callback_maps_http_status_error_to_400(client, monkeypatch):
    import httpx

    async def fake(code: str):
        # Simulate a bad authorization code from Google.
        req = httpx.Request("POST", "https://oauth2.googleapis.com/token")
        resp = httpx.Response(400, request=req)
        raise httpx.HTTPStatusError("bad code", request=req, response=resp)

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)
    client.cookies.set("oauth_state", "fake-state")
    r = await client.get("/auth/google/callback", params={"code": "X", "state": "fake-state"})
    assert r.status_code == 400


async def test_google_callback_maps_request_error_to_502(client, monkeypatch):
    import httpx

    async def fake(code: str):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)
    client.cookies.set("oauth_state", "fake-state")
    r = await client.get("/auth/google/callback", params={"code": "X", "state": "fake-state"})
    assert r.status_code == 502


async def test_callback_without_state_cookie_rejected(client):
    r = await client.get("/auth/google/callback", params={"code": "x", "state": "y"})
    assert r.status_code == 400


async def test_callback_with_mismatched_state_rejected(client):
    client.cookies.set("oauth_state", "server-state")
    r = await client.get(
        "/auth/google/callback",
        params={"code": "x", "state": "attacker-state"},
    )
    assert r.status_code == 400
