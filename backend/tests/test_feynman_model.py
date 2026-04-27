from app.models import FeynmanSession, FeynmanKind


def test_feynman_session_columns():
    cols = FeynmanSession.__table__.columns.keys()
    for c in (
        "id", "user_id", "paper_id", "target_concept_id",
        "kind", "started_at", "ended_at",
        "quality_score", "transcript",
    ):
        assert c in cols


def test_feynman_kind_enum_values():
    assert FeynmanKind.fresh.value == "fresh"
    assert FeynmanKind.scheduled.value == "scheduled"
