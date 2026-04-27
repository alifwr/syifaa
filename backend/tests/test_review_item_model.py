from app.models import ReviewItem


def test_review_item_columns():
    cols = ReviewItem.__table__.columns.keys()
    for c in (
        "id", "user_id", "concept_id", "embed_dim",
        "ease", "interval_days", "due_at",
        "last_session_id", "last_score",
        "created_at", "updated_at",
    ):
        assert c in cols


def test_review_item_unique_index_on_user_concept_dim():
    indexes = {ix.name: ix for ix in ReviewItem.__table__.indexes}
    assert "uq_review_item_user_concept_dim" in indexes
    assert indexes["uq_review_item_user_concept_dim"].unique is True
