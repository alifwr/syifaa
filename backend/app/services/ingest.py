"""Paper ingest orchestration: blob → text → chunks+embeds → concepts → edges.

Contract:
    ingest_paper(paper_id, db, gateway, storage, embed_dim) -> None
    On success: paper.status = parsed, chunks + concepts + edges persisted.
    On failure: paper.status = failed, paper.parse_error populated. No partial
    chunks remain for the failed paper (we commit at the end).
"""
import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Paper, PaperStatus, chunk_model_for, concept_model_for, ConceptEdge
from app.services.pdf_ingest import chunk_text, extract_text, approx_token_count

log = logging.getLogger("syifa.ingest")


_CONCEPT_PROMPT = (
    "You are extracting the key scientific concepts from a research paper. "
    "Return STRICT JSON of the form "
    '{"concepts":[{"name": "...", "summary": "one sentence"}]} '
    "with at most 12 concepts. No commentary."
)


async def ingest_paper(
    *,
    paper_id: UUID,
    db: AsyncSession,
    gateway,
    storage,
    embed_dim: int,
) -> None:
    settings = get_settings()
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()
    try:
        blob = await storage.get_object(paper.s3_key)
        text = extract_text(blob)
        if not text:
            raise ValueError("extracted text is empty")
        paper.text_hash = hashlib.sha256(text.encode()).hexdigest()

        chunks = chunk_text(
            text,
            max_tokens=settings.paper_chunk_max_tokens,
            overlap=settings.paper_chunk_overlap,
        )
        if not chunks:
            raise ValueError("no chunks produced")

        chunk_embeds = await gateway.embed(chunks)
        if len(chunk_embeds) != len(chunks):
            raise ValueError("embedding count mismatch for chunks")

        ChunkM = chunk_model_for(embed_dim)
        # Idempotent re-ingest: clear prior chunks for this paper.
        await db.execute(delete(ChunkM).where(ChunkM.paper_id == paper.id))
        for i, (c, e) in enumerate(zip(chunks, chunk_embeds)):
            db.add(ChunkM(paper_id=paper.id, ord=i, text=c, tokens=approx_token_count(c), embedding=e))

        # Concept extraction: single LLM call, JSON-parsed.
        head = "\n\n".join(chunks[:3])
        msg = [
            {"role": "system", "content": _CONCEPT_PROMPT},
            {"role": "user", "content": head},
        ]
        resp = await gateway.chat(msg)
        content = resp.choices[0].message.content
        data = json.loads(content)
        concept_records = (data.get("concepts") or [])[:12]
        if not concept_records:
            log.warning("no concepts extracted for paper %s", paper.id)
        else:
            names = [c["name"] for c in concept_records]
            concept_embeds = await gateway.embed(names)
            ConceptM = concept_model_for(embed_dim)
            new_concepts = []
            for rec, vec in zip(concept_records, concept_embeds):
                obj = ConceptM(
                    user_id=paper.user_id,
                    name=rec["name"][:500],
                    summary=rec.get("summary", "")[:2000],
                    source_paper_ids=[paper.id],
                    embedding=vec,
                )
                db.add(obj)
                new_concepts.append(obj)
            await db.flush()  # assign IDs before building edges

            # Propose edges: cosine to existing concepts of same user.
            await _propose_edges(
                db, ConceptM, new_concepts, user_id=paper.user_id,
                top_k=settings.concept_edge_top_k,
                min_cos=settings.concept_edge_min_cosine,
            )

        paper.status = PaperStatus.parsed
        paper.parse_error = None
        await db.commit()
    except Exception as e:
        log.exception("ingest failed for paper %s", paper_id)
        try:
            await db.rollback()
            paper = (
                await db.execute(select(Paper).where(Paper.id == paper_id))
            ).scalar_one()
            paper.status = PaperStatus.failed
            paper.parse_error = str(e)[:2000]
            await db.commit()
        except Exception:
            log.exception("could not persist failure state for paper %s", paper_id)


async def _propose_edges(db, ConceptM, new_concepts, *, user_id, top_k, min_cos):
    if len(new_concepts) < 2:
        return
    # In-memory dedup so we don't rely on session autoflush picking up adds
    # made earlier in this call. Also skips a SELECT per candidate pair.
    added: set[frozenset] = set()
    for new in new_concepts:
        dist_col = ConceptM.embedding.cosine_distance(new.embedding).label("d")
        result = await db.execute(
            select(ConceptM, dist_col)
            .where(ConceptM.user_id == user_id, ConceptM.id != new.id)
            .order_by(dist_col)
            .limit(top_k)
        )
        for other, dist in result.all():
            cos = 1.0 - float(dist)
            if cos < min_cos:
                continue
            pair = frozenset({new.id, other.id})
            if pair in added:
                continue
            exists = (
                await db.execute(
                    select(ConceptEdge).where(
                        ConceptEdge.user_id == user_id,
                        ((ConceptEdge.src_id == new.id) & (ConceptEdge.dst_id == other.id))
                        | ((ConceptEdge.src_id == other.id) & (ConceptEdge.dst_id == new.id)),
                    )
                )
            ).scalar_one_or_none()
            if exists:
                continue
            db.add(
                ConceptEdge(
                    user_id=user_id, src_id=new.id, dst_id=other.id,
                    relation="related-to", confidence=cos,
                )
            )
            added.add(pair)
