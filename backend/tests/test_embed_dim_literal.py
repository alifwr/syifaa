import pytest
from pydantic import ValidationError
from app.schemas.llm_config import LLMConfigIn


def _payload(dim: int) -> dict:
    return {
        "name": "n", "chat_base_url": "http://x/v1", "chat_api_key": "sk",
        "chat_model": "m", "embed_base_url": "http://x/v1", "embed_api_key": "sk",
        "embed_model": "em", "embed_dim": dim,
    }


def test_embed_dim_768_accepted():
    LLMConfigIn(**_payload(768))


def test_embed_dim_1024_accepted():
    LLMConfigIn(**_payload(1024))


def test_embed_dim_1536_accepted():
    LLMConfigIn(**_payload(1536))


@pytest.mark.parametrize("bad", [512, 2048, 0, 1])
def test_embed_dim_unsupported_rejected(bad: int):
    with pytest.raises(ValidationError):
        LLMConfigIn(**_payload(bad))
