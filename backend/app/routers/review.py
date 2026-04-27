from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import LLMConfig, ReviewItem, concept_model_for
from app.schemas.review import ReviewItemOut

router = APIRouter(prefix="/review", tags=["review"])


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.get("/due", response_model=list[ReviewItemOut])
async def due(user: CurrentUser, db: DbSession) -> list[ReviewItemOut]:
    dim = await _resolve_active_dim(db, user.id)
    if dim is None:
        raise HTTPException(status_code=400, detail="No active LLM config")

    ConceptM = concept_model_for(dim)
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.user_id == user.id,
                ReviewItem.embed_dim == dim,
                ReviewItem.due_at <= now,
            ).order_by(ReviewItem.due_at)
        )
    ).scalars().all()

    if not rows:
        return []

    cids = [r.concept_id for r in rows]
    concepts = (
        await db.execute(
            select(ConceptM).where(ConceptM.id.in_(cids))
        )
    ).scalars().all()
    name_by_id = {c.id: c.name for c in concepts}

    return [
        ReviewItemOut(
            id=r.id, concept_id=r.concept_id,
            concept_name=name_by_id.get(r.concept_id, "(missing)"),
            embed_dim=r.embed_dim, ease=r.ease,
            interval_days=r.interval_days, due_at=r.due_at,
            last_score=float(r.last_score) if r.last_score is not None else None,
        )
        for r in rows
    ]
