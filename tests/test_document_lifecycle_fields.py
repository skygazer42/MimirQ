from __future__ import annotations


def test_document_lifecycle_fields_exist_on_models_and_schema():  # noqa: ANN001
    """
    Ops-T021: ensure lifecycle fields are first-class and discoverable.

    This is intentionally a lightweight unit test (no DB required):
    - ORM: columns exist on Document model (migration responsibility handled elsewhere)
    - API: DocumentDetail schema exposes these fields for ops/governance workflows
    """

    from app.api.schemas.document import DocumentDetail
    from app.models.document import Document as DBDocument

    # ORM columns (SQLAlchemy mapped attributes)
    for attr in (
        "lifecycle_owner",
        "review_due_at",
        "authority_level",
        "supersedes_document_id",
    ):
        assert hasattr(DBDocument, attr), f"Document model missing lifecycle field: {attr}"

    # API schema fields (Pydantic v2)
    for field in (
        "lifecycle_owner",
        "review_due_at",
        "authority_level",
        "supersedes_document_id",
    ):
        assert field in DocumentDetail.model_fields, f"DocumentDetail missing lifecycle field: {field}"

