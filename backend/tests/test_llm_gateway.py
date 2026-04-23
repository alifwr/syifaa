import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm_gateway import LLMGateway, LLMConnectionError


def _cfg(**kw):
    return {
        "chat_base_url": "http://chat/v1",
        "chat_api_key": "k1",
        "chat_model": "gpt-mock",
        "embed_base_url": "http://embed/v1",
        "embed_api_key": "k2",
        "embed_model": "emb-mock",
        "embed_dim": 8,
        **kw,
    }


@pytest.mark.asyncio
async def test_ping_chat_success():
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="pong"))])
    )
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg())
        assert await gw.ping_chat() is True


@pytest.mark.asyncio
async def test_ping_chat_failure_raises():
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("401 unauthorized"))
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg())
        with pytest.raises(LLMConnectionError) as exc:
            await gw.ping_chat()
        assert "401" in str(exc.value)


@pytest.mark.asyncio
async def test_ping_embed_validates_dim():
    fake = MagicMock()
    fake.embeddings.create = AsyncMock(
        return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 8)])
    )
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg(embed_dim=8))
        assert await gw.ping_embed() is True


@pytest.mark.asyncio
async def test_ping_embed_dim_mismatch_raises():
    fake = MagicMock()
    fake.embeddings.create = AsyncMock(
        return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 4)])
    )
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg(embed_dim=8))
        with pytest.raises(LLMConnectionError) as exc:
            await gw.ping_embed()
        assert "dim" in str(exc.value).lower()
