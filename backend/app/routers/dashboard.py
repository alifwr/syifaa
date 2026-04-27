from fastapi import APIRouter
from sqlalchemy import select, func

from app.deps import CurrentUser, DbSession
from app.models import FeynmanSession, LLMConfig, concept_model_for
from app.schemas.dashboard import DashboardOut, SessionScorePoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RECENT_SESSIONS_LIMIT = 30


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.get("", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: DbSession) -> DashboardOut:
    dim = await _resolve_active_dim(db, user.id)
    concept_count = 0
    if dim is not None:
        ConceptM = concept_model_for(dim)
        concept_count = (
            await db.execute(
                select(func.count()).select_from(ConceptM)
                .where(ConceptM.user_id == user.id)
            )
        ).scalar() or 0

    rows = (
        await db.execute(
            select(FeynmanSession)
            .where(
                FeynmanSession.user_id == user.id,
                FeynmanSession.ended_at.is_not(None),
                FeynmanSession.quality_score.is_not(None),
            )
            .order_by(FeynmanSession.started_at.desc())
            .limit(_RECENT_SESSIONS_LIMIT)
        )
    ).scalars().all()

    sessions = [
        SessionScorePoint(
            started_at=r.started_at,
            quality_score=float(r.quality_score),
        )
        for r in rows
    ]
    return DashboardOut(concept_count=concept_count, sessions=sessions)
