from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMConfig, User
from app.security import decrypt_secret
from app.services.llm_gateway import LLMGateway


class NoActiveLLMConfig(Exception):
    pass


def build_gateway_from_config(cfg: LLMConfig) -> LLMGateway:
    return LLMGateway(
        chat_base_url=cfg.chat_base_url,
        chat_api_key=decrypt_secret(cfg.chat_api_key_enc),
        chat_model=cfg.chat_model,
        embed_base_url=cfg.embed_base_url,
        embed_api_key=decrypt_secret(cfg.embed_api_key_enc),
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
    )


async def build_user_gateway(db: AsyncSession, user: User) -> LLMGateway:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise NoActiveLLMConfig("user has no active LLM config")
    return build_gateway_from_config(cfg)
