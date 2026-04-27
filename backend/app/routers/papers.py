import logging
from uuid import UUID, uuid4

from fastapi import (
    APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status,
)
from sqlalchemy import select
from sqlalchemy import delete as sa_delete

from app.deps import CurrentUser, DbSession
from app.db import get_sessionmaker
from app.models import Paper, PaperStatus, LLMConfig
from app.models import Concept768, Concept1024, Concept1536, ConceptEdge
from app.schemas.paper import PaperOut
from app.services.storage import Storage
from app.services.user_llm import build_user_gateway, NoActiveLLMConfig
from app.services.ingest import ingest_paper

log = logging.getLogger("syifa.papers")
router = APIRouter(prefix="/papers", tags=["papers"])


def _to_out(p: Paper) -> PaperOut:
    return PaperOut(
        id=p.id, title=p.title, authors=p.authors or "",
        uploaded_at=p.uploaded_at, status=p.status.value,
        parse_error=p.parse_error,
    )


async def _run_ingest(paper_id: UUID, user_id: UUID, embed_dim: int) -> None:
    """Runs in BackgroundTasks; opens its own session."""
    maker = get_sessionmaker()
    async with maker() as db:
        from app.models import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        try:
            gw = await build_user_gateway(db, u)
        except NoActiveLLMConfig:
            log.error("no active config for user %s during ingest", user_id)
            return
        await ingest_paper(
            paper_id=paper_id, db=db, gateway=gw, storage=Storage(),
            embed_dim=embed_dim,
        )


@router.post("", response_model=PaperOut, status_code=status.HTTP_201_CREATED)
async def upload(
    user: CurrentUser,
    db: DbSession,
    bg: BackgroundTasks,
    title: str = Form(...),
    file: UploadFile = File(...),
) -> PaperOut:
    if (file.content_type or "").lower() not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=415, detail="Only PDF uploads accepted")

    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config; set one in settings")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    key = f"papers/{user.id}/{uuid4()}.pdf"
    await Storage().put_object(key, data, content_type="application/pdf")

    paper = Paper(user_id=user.id, title=title[:500], s3_key=key, status=PaperStatus.uploaded)
    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    bg.add_task(_run_ingest, paper.id, user.id, cfg.embed_dim)
    return _to_out(paper)


@router.get("", response_model=list[PaperOut])
async def list_(user: CurrentUser, db: DbSession) -> list[PaperOut]:
    rows = (
        await db.execute(
            select(Paper).where(Paper.user_id == user.id).order_by(Paper.uploaded_at.desc())
        )
    ).scalars().all()
    return [_to_out(p) for p in rows]


@router.get("/{pid}", response_model=PaperOut)
async def get_one(pid: UUID, user: CurrentUser, db: DbSession) -> PaperOut:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return _to_out(p)


@router.post("/{pid}/reingest", response_model=PaperOut)
async def reingest(
    pid: UUID, user: CurrentUser, db: DbSession, bg: BackgroundTasks,
) -> PaperOut:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    p.status = PaperStatus.uploaded
    p.parse_error = None
    await db.commit()
    await db.refresh(p)
    bg.add_task(_run_ingest, p.id, user.id, cfg.embed_dim)
    return _to_out(p)


async def _prune_concepts_for_paper(db, user_id, pid) -> None:
    for ConceptM in (Concept768, Concept1024, Concept1536):
        rows = (
            await db.execute(
                select(ConceptM).where(ConceptM.user_id == user_id)
            )
        ).scalars().all()
        for r in rows:
            srcs = list(r.source_paper_ids or [])
            if pid not in srcs:
                continue
            srcs = [s for s in srcs if s != pid]
            if srcs:
                r.source_paper_ids = srcs
                continue
            await db.execute(
                sa_delete(ConceptEdge).where(
                    ConceptEdge.user_id == user_id,
                    (ConceptEdge.src_id == r.id) | (ConceptEdge.dst_id == r.id),
                )
            )
            await db.delete(r)


@router.delete("/{pid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(pid: UUID, user: CurrentUser, db: DbSession) -> None:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        await Storage().delete_object(p.s3_key)
    except Exception:
        log.warning("blob %s not deleted; continuing", p.s3_key)
    await _prune_concepts_for_paper(db, user.id, p.id)
    await db.delete(p)
    await db.commit()
