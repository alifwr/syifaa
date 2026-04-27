from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl


class LLMConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chat_base_url: HttpUrl
    chat_api_key: str = Field(min_length=1, max_length=500)
    chat_model: str = Field(min_length=1, max_length=200)
    embed_base_url: HttpUrl
    embed_api_key: str = Field(min_length=1, max_length=500)
    embed_model: str = Field(min_length=1, max_length=200)
    embed_dim: Literal[768, 1024, 1536]


class LLMConfigOut(BaseModel):
    id: UUID
    name: str
    chat_base_url: str
    chat_model: str
    embed_base_url: str
    embed_model: str
    embed_dim: int
    is_active: bool


class TestConnectionOut(BaseModel):
    chat: str
    embed: str
