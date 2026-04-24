import pytest
from app.db import get_sessionmaker
from app.models import User, LLMConfig
from app.security import encrypt_secret
from app.services.user_llm import (
    NoActiveLLMConfig,
    build_user_gateway,
    build_gateway_from_config,
)


def _mk_user_and_cfg(active: bool) -> tuple[User, LLMConfig]:
    u = User(email="x@y.z", pw_hash="h")
    c = LLMConfig(
        user_id=None,  # set after user insert
        name="n",
        chat_base_url="http://c/v1",
        chat_api_key_enc=encrypt_secret("sk-chat"),
        chat_model="cm",
        embed_base_url="http://e/v1",
        embed_api_key_enc=encrypt_secret("sk-embed"),
        embed_model="em",
        embed_dim=1536,
        is_active=active,
    )
    return u, c


async def test_build_gateway_from_config_decrypts_keys(fernet_key):
    _, cfg = _mk_user_and_cfg(active=True)
    gw = build_gateway_from_config(cfg)
    assert gw._chat_model == "cm"
    assert gw._embed_model == "em"
    assert gw._embed_dim == 1536


async def test_build_user_gateway_picks_active(fernet_key, fresh_schema):
    maker = get_sessionmaker()
    async with maker() as db:
        u, c = _mk_user_and_cfg(active=True)
        db.add(u)
        await db.commit()
        c.user_id = u.id
        db.add(c)
        await db.commit()
        gw = await build_user_gateway(db, u)
        assert gw._chat_model == "cm"


async def test_build_user_gateway_raises_without_active(fernet_key, fresh_schema):
    maker = get_sessionmaker()
    async with maker() as db:
        u, c = _mk_user_and_cfg(active=False)
        db.add(u)
        await db.commit()
        c.user_id = u.id
        db.add(c)
        await db.commit()
        with pytest.raises(NoActiveLLMConfig):
            await build_user_gateway(db, u)
