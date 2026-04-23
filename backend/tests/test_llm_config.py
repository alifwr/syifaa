import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine


@pytest.fixture
async def client(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    # Re-read settings for the newly installed key.
    from app.config import get_settings
    get_settings.cache_clear()

    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _auth_header(client):
    await client.post(
        "/auth/signup",
        json={"email": "u@b.com", "password": "pw_long_enough_xx"},
    )
    tok = (
        await client.post(
            "/auth/login",
            json={"email": "u@b.com", "password": "pw_long_enough_xx"},
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


_PAYLOAD = {
    "name": "openrouter",
    "chat_base_url": "https://openrouter.ai/api/v1",
    "chat_api_key": "sk-or-xyz",
    "chat_model": "anthropic/claude-3.5-sonnet",
    "embed_base_url": "https://api.openai.com/v1",
    "embed_api_key": "sk-openai-xyz",
    "embed_model": "text-embedding-3-small",
    "embed_dim": 1536,
}


async def test_create_llm_config_requires_auth(client):
    r = await client.post("/llm-config", json=_PAYLOAD)
    assert r.status_code == 401


async def test_create_and_list_llm_config(client):
    h = await _auth_header(client)
    r = await client.post("/llm-config", json=_PAYLOAD, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "openrouter"
    assert "chat_api_key" not in body
    assert "chat_api_key_enc" not in body
    assert "embed_api_key" not in body
    assert "embed_api_key_enc" not in body

    r2 = await client.get("/llm-config", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()) == 1


async def test_activate_llm_config(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    r = await client.post(f"/llm-config/{cid}/activate", headers=h)
    assert r.status_code == 200
    r2 = await client.get("/llm-config", headers=h)
    active = [c for c in r2.json() if c["is_active"]]
    assert len(active) == 1 and active[0]["id"] == cid


async def test_test_connection_success(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    with patch("app.routers.llm_config.LLMGateway") as GW:
        inst = GW.return_value
        inst.ping_chat = AsyncMock(return_value=True)
        inst.ping_embed = AsyncMock(return_value=True)
        r = await client.post(f"/llm-config/{cid}/test", headers=h)
    assert r.status_code == 200
    assert r.json() == {"chat": "ok", "embed": "ok"}


async def test_test_connection_chat_failure_reports_error(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    with patch("app.routers.llm_config.LLMGateway") as GW:
        inst = GW.return_value
        from app.services.llm_gateway import LLMConnectionError

        inst.ping_chat = AsyncMock(side_effect=LLMConnectionError("401 unauthorized"))
        inst.ping_embed = AsyncMock(return_value=True)
        r = await client.post(f"/llm-config/{cid}/test", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["chat"].startswith("error:")
    assert body["embed"] == "ok"


async def test_delete_llm_config_success(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    r = await client.delete(f"/llm-config/{cid}", headers=h)
    assert r.status_code == 204
    r2 = await client.get("/llm-config", headers=h)
    assert r2.json() == []


async def test_delete_llm_config_not_found(client):
    h = await _auth_header(client)
    from uuid import uuid4
    r = await client.delete(f"/llm-config/{uuid4()}", headers=h)
    assert r.status_code == 404


async def test_delete_llm_config_other_user_404(client):
    # User A creates a config; User B must get 404 on delete attempt.
    ha = await _auth_header(client)  # u@b.com from helper
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=ha)).json()["id"]

    await client.post("/auth/signup", json={"email": "other@b.com", "password": "pw_long_enough_xx"})
    tok_b = (await client.post("/auth/login", json={
        "email": "other@b.com", "password": "pw_long_enough_xx"
    })).json()["access_token"]
    hb = {"Authorization": f"Bearer {tok_b}"}

    r = await client.delete(f"/llm-config/{cid}", headers=hb)
    assert r.status_code == 404
    # And the row is still there for user A.
    r2 = await client.get("/llm-config", headers=ha)
    assert len(r2.json()) == 1
