import pytest
from app.models import (
    Paper, PaperChunk768, PaperChunk1024, PaperChunk1536,
    Concept768, Concept1024, Concept1536, ConceptEdge,
    chunk_model_for, concept_model_for,
)


def test_chunk_model_for_maps_known_dims():
    assert chunk_model_for(768) is PaperChunk768
    assert chunk_model_for(1024) is PaperChunk1024
    assert chunk_model_for(1536) is PaperChunk1536


def test_concept_model_for_maps_known_dims():
    assert concept_model_for(768) is Concept768
    assert concept_model_for(1024) is Concept1024
    assert concept_model_for(1536) is Concept1536


def test_unknown_dim_raises():
    with pytest.raises(ValueError):
        chunk_model_for(999)
    with pytest.raises(ValueError):
        concept_model_for(999)


def test_paper_has_status_and_parse_error():
    cols = Paper.__table__.columns.keys()
    for c in ("id", "user_id", "title", "authors", "uploaded_at",
              "s3_key", "text_hash", "status", "parse_error"):
        assert c in cols
