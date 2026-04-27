import logging
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.deps import CurrentUser, DbSession
from app.models import (
    FeynmanSession, FeynmanKind, LLMConfig, Paper, concept_model_for,
)
from app.schemas.feynman import (
    FeynmanStartIn, FeynmanSessionOut, FeynmanMessageIn,
)
from app.services.feynman import build_system_prompt
from app.services.sse import sse_event, stream_chat
from app.services.user_llm import build_user_gateway

log = logging.getLogger("syifa.feynman")
router = APIRouter(prefix="/feynman", tags=["feynman"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_out(s: FeynmanSession) -> FeynmanSessionOut:
    return FeynmanSessionOut(
        id=s.id, user_id=s.user_id, paper_id=s.paper_id,
        target_concept_id=s.target_concept_id, kind=s.kind.value,
        started_at=s.started_at, ended_at=s.ended_at,
        quality_score=float(s.quality_score) if s.quality_score is not None else None,
        transcript=s.transcript or [],
    )


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.post("/start", response_model=FeynmanSessionOut, status_code=status.HTTP_201_CREATED)
async def start(data: FeynmanStartIn, user: CurrentUser, db: DbSession) -> FeynmanSessionOut:
    dim = await _resolve_active_dim(db, user.id)
    if dim is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    ConceptM = concept_model_for(dim)

    if data.paper_id is not None:
        paper = (
            await db.execute(
                select(Paper).where(Paper.id == data.paper_id, Paper.user_id == user.id)
            )
        ).scalar_one_or_none()
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        candidate = (
            await db.execute(
                select(ConceptM).where(
                    ConceptM.user_id == user.id,
                    ConceptM.source_paper_ids.any(paper.id),
                ).order_by(ConceptM.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    else:
        paper = None
        candidate = (
            await db.execute(
                select(ConceptM).where(ConceptM.user_id == user.id)
                .order_by(ConceptM.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

    if candidate is None:
        raise HTTPException(status_code=400, detail="No concepts available; ingest a paper first")

    sys_prompt = build_system_prompt(
        concept_name=candidate.name, concept_summary=candidate.summary,
    )
    transcript = [{
        "role": "system",
        "content": sys_prompt,
        "ts": datetime.now(timezone.utc).isoformat(),
    }]

    session = FeynmanSession(
        user_id=user.id,
        paper_id=paper.id if paper else None,
        target_concept_id=candidate.id,
        kind=FeynmanKind(data.kind),
        transcript=transcript,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _to_out(session)


@router.get("/{sid}", response_model=FeynmanSessionOut)
async def get_one(sid: UUID, user: CurrentUser, db: DbSession) -> FeynmanSessionOut:
    s = (
        await db.execute(
            select(FeynmanSession).where(
                FeynmanSession.id == sid, FeynmanSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_out(s)


@router.post("/{sid}/message")
async def message(
    sid: UUID,
    data: FeynmanMessageIn,
    user: CurrentUser,
    db: DbSession,
):
    s = (
        await db.execute(
            select(FeynmanSession).where(
                FeynmanSession.id == sid, FeynmanSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.ended_at is not None:
        raise HTTPException(status_code=400, detail="Session already ended")

    gw = await build_user_gateway(db, user)

    user_turn = {"role": "user", "content": data.content, "ts": _now_iso()}
    s.transcript = list(s.transcript or []) + [user_turn]
    flag_modified(s, "transcript")
    await db.commit()

    llm_msgs = [{"role": t["role"], "content": t["content"]} for t in s.transcript]

    async def gen() -> AsyncIterator[bytes]:
        full: list[str] = []
        try:
            async for delta, finish in stream_chat(gw, llm_msgs):
                if delta:
                    full.append(delta)
                    yield sse_event(delta)
                if finish:
                    break
        except Exception as e:
            log.exception("stream failed for session %s", sid)
            yield sse_event({"error": str(e)})
        finally:
            assistant = "".join(full).strip()
            if assistant:
                fresh = (
                    await db.execute(
                        select(FeynmanSession).where(FeynmanSession.id == sid)
                    )
                ).scalar_one()
                fresh.transcript = list(fresh.transcript or []) + [{
                    "role": "assistant", "content": assistant, "ts": _now_iso(),
                }]
                flag_modified(fresh, "transcript")
                await db.commit()
            yield sse_event("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")
