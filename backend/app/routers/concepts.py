from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import LLMConfig, concept_model_for
from app.schemas.concept import ConceptOut

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("", response_model=list[ConceptOut])
async def list_(user: CurrentUser, db: DbSession) -> list[ConceptOut]:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    M = concept_model_for(cfg.embed_dim)
    rows = (
        await db.execute(
            select(M).where(M.user_id == user.id).order_by(M.created_at.desc())
        )
    ).scalars().all()
    return [
        ConceptOut(id=r.id, name=r.name, summary=r.summary, stage=r.stage.value)
        for r in rows
    ]
