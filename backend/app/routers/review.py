from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import FeynmanSession, FeynmanKind, LLMConfig, ReviewItem, concept_model_for
from app.schemas.feynman import FeynmanSessionOut
from app.schemas.review import ReviewItemOut, ReviewStartIn
from app.services.feynman import build_system_prompt

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


@router.post("/start", response_model=FeynmanSessionOut, status_code=status.HTTP_201_CREATED)
async def start_review(
    data: ReviewStartIn, user: CurrentUser, db: DbSession,
) -> FeynmanSessionOut:
    item = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.id == data.review_item_id,
                ReviewItem.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    ConceptM = concept_model_for(item.embed_dim)
    concept = (
        await db.execute(
            select(ConceptM).where(
                ConceptM.id == item.concept_id, ConceptM.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if concept is None:
        raise HTTPException(status_code=404, detail="Concept not found for review item")

    sys_prompt = build_system_prompt(
        concept_name=concept.name, concept_summary=concept.summary,
    )
    transcript = [{
        "role": "system",
        "content": sys_prompt,
        "ts": datetime.now(timezone.utc).isoformat(),
    }]
    session = FeynmanSession(
        user_id=user.id,
        paper_id=None,
        target_concept_id=concept.id,
        kind=FeynmanKind.scheduled,
        embed_dim=item.embed_dim,
        transcript=transcript,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    visible = [t for t in session.transcript if t.get("role") != "system"]
    return FeynmanSessionOut(
        id=session.id, user_id=session.user_id, paper_id=session.paper_id,
        target_concept_id=session.target_concept_id, kind=session.kind.value,
        started_at=session.started_at, ended_at=session.ended_at,
        quality_score=None,
        transcript=visible,
    )
