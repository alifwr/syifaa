from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.deps import DbSession, CurrentUser
from app.models import LLMConfig
from app.schemas.llm_config import LLMConfigIn, LLMConfigOut, TestConnectionOut
from app.security import encrypt_secret, decrypt_secret
from app.services.llm_gateway import LLMGateway, LLMConnectionError


router = APIRouter(prefix="/llm-config", tags=["llm-config"])


def _to_out(c: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=c.id,
        name=c.name,
        chat_base_url=c.chat_base_url,
        chat_model=c.chat_model,
        embed_base_url=c.embed_base_url,
        embed_model=c.embed_model,
        embed_dim=c.embed_dim,
        is_active=c.is_active,
    )


@router.post("", response_model=LLMConfigOut, status_code=status.HTTP_201_CREATED)
async def create(data: LLMConfigIn, user: CurrentUser, db: DbSession) -> LLMConfigOut:
    cfg = LLMConfig(
        user_id=user.id,
        name=data.name,
        chat_base_url=str(data.chat_base_url).rstrip("/"),
        chat_api_key_enc=encrypt_secret(data.chat_api_key),
        chat_model=data.chat_model,
        embed_base_url=str(data.embed_base_url).rstrip("/"),
        embed_api_key_enc=encrypt_secret(data.embed_api_key),
        embed_model=data.embed_model,
        embed_dim=data.embed_dim,
        is_active=False,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)


@router.get("", response_model=list[LLMConfigOut])
async def list_(user: CurrentUser, db: DbSession) -> list[LLMConfigOut]:
    rows = (
        await db.execute(
            select(LLMConfig)
            .where(LLMConfig.user_id == user.id)
            .order_by(LLMConfig.created_at)
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("/{cid}/activate", response_model=LLMConfigOut)
async def activate(cid: UUID, user: CurrentUser, db: DbSession) -> LLMConfigOut:
    target = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == cid, LLMConfig.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.execute(
        update(LLMConfig)
        .where(LLMConfig.user_id == user.id)
        .values(is_active=False)
    )
    target.is_active = True
    await db.commit()
    await db.refresh(target)
    return _to_out(target)


@router.delete("/{cid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(cid: UUID, user: CurrentUser, db: DbSession) -> None:
    target = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == cid, LLMConfig.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.delete(target)
    await db.commit()


@router.post("/{cid}/test", response_model=TestConnectionOut)
async def test_connection(
    cid: UUID, user: CurrentUser, db: DbSession
) -> TestConnectionOut:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == cid, LLMConfig.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")

    gw = LLMGateway(
        chat_base_url=cfg.chat_base_url,
        chat_api_key=decrypt_secret(cfg.chat_api_key_enc),
        chat_model=cfg.chat_model,
        embed_base_url=cfg.embed_base_url,
        embed_api_key=decrypt_secret(cfg.embed_api_key_enc),
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
    )

    async def _safe(coro) -> str:
        try:
            await coro
            return "ok"
        except LLMConnectionError as e:
            return f"error: {e}"

    return TestConnectionOut(
        chat=await _safe(gw.ping_chat()),
        embed=await _safe(gw.ping_embed()),
    )
