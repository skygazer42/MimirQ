from __future__ import annotations

import uuid


def test_document_failure_fields_exist_on_models_and_schemas() -> None:
    from app.api.schemas.document import DocumentDetail, DocumentStatus
    from app.models.document import Document as DBDocument

    for attr in ("failed_stage", "error_code", "processing_attempts", "next_retry_at"):
        assert hasattr(DBDocument, attr), f"Document model missing ingest failure field: {attr}"

    for schema in (DocumentDetail, DocumentStatus):
        for field in ("failed_stage", "error_code", "processing_attempts", "next_retry_at"):
            assert field in schema.model_fields, f"{schema.__name__} missing ingest failure field: {field}"


class _FakeQuery:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def filter(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
        return self

    def first(self):  # noqa: ANN201
        return self._db.dead_letters[0] if self._db.dead_letters else None


class _FakeDB:
    def __init__(self) -> None:
        self.dead_letters: list[object] = []
        self.commits = 0

    def query(self, _model):  # noqa: ANN001, ANN201
        return _FakeQuery(self)

    def add(self, obj: object) -> None:
        self.dead_letters.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj: object) -> None:
        return None


class _Document:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.dataset_id = uuid.uuid4()
        self.filename = "demo.pdf"
        self.file_type = "pdf"
        self.file_path = "/tmp/demo.pdf"
        self.doc_metadata = {"task_id": "task-1", "pipeline_hash": "ph1"}
        self.failed_stage = None
        self.error_code = None
        self.processing_attempts = 0
        self.next_retry_at = None


def test_record_ingest_dead_letter_stamps_document_and_reuses_open_letter() -> None:
    from app.services.ingest_dead_letter_service import record_ingest_dead_letter

    db = _FakeDB()
    doc = _Document()

    first = record_ingest_dead_letter(
        db,
        document=doc,
        failed_stage="embedding",
        error_message="TimeoutError: embedding provider down",
        original_payload={"job_id": "doc-job"},
    )
    second = record_ingest_dead_letter(
        db,
        document=doc,
        failed_stage="embedding",
        error_message="TimeoutError: embedding provider down again",
        original_payload={"job_id": "doc-job"},
    )

    assert first is second
    assert len(db.dead_letters) == 1
    assert doc.failed_stage == "embedding"
    assert doc.error_code == "timeout"
    assert doc.processing_attempts == 2
    assert first.status == "open"
    assert first.error_code == "timeout"
    assert first.retry_count == 1
    assert first.original_payload["job_id"] == "doc-job"


def test_documents_router_exposes_dead_letter_routes_before_document_detail_route() -> None:
    from app.api.v1.documents import router

    paths = [getattr(route, "path", "") for route in router.routes]

    assert "/dead-letters" in paths
    assert "/dead-letters/{dead_letter_id}/replay" in paths
    assert paths.index("/dead-letters") < paths.index("/{document_id}")
