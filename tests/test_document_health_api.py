from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeQuery:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = rows
        self._limit: int | None = None

    def filter(self, *_args, **_kwargs):  # noqa: ANN001, ANN202
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001, ANN202
        return self

    def limit(self, value: int):  # noqa: ANN001, ANN202
        self._limit = value
        return self

    def all(self):  # noqa: ANN202
        if not isinstance(self._rows, list):
            return []
        if self._limit is None:
            return self._rows
        return self._rows[: self._limit]

    def first(self):  # noqa: ANN202
        return self._rows


class _FakeDB:
    def __init__(self, *, docs_module, document, chunk_ranges, chunk_contents) -> None:  # noqa: ANN001
        self._docs_module = docs_module
        self._document = document
        self._chunk_ranges = chunk_ranges
        self._chunk_contents = chunk_contents

    def query(self, *entities):  # noqa: ANN001, ANN202
        if len(entities) == 1 and entities[0] is self._docs_module.DBDocument:
            return _FakeQuery(self._document)

        keys = [getattr(entity, "key", None) for entity in entities]
        if keys == ["start_char", "end_char"]:
            return _FakeQuery(self._chunk_ranges)
        if keys == ["content"]:
            return _FakeQuery(self._chunk_contents)

        raise AssertionError(f"Unexpected query entities: {entities!r}")


def test_document_health_card_endpoint_aggregates_parsing_chunking_kg_and_hits(monkeypatch):  # noqa: ANN001
    import app.api.v1.document_health as document_health_module
    import app.api.v1.documents as documents_module

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    class _Document:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.filename = "demo.pdf"
            self.file_type = "application/pdf"
            self.file_size = 2048
            self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            self.updated_at = datetime(2026, 1, 2, tzinfo=UTC)
            self.processed_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
            self.status = "completed"
            self.total_characters = 100
            self.chunk_count = 2
            self.doc_metadata = {
                "parser_backend": "docling",
                "parser_backend_requested": "docling",
                "parse_quality": {"score": 0.25},
                "pdf_quality": {"is_scanned": True, "page_count": 3},
                "seal_summary": {
                    "detected": True,
                    "count": 1,
                    "candidate_count_total": 2,
                    "primary_text": "杭州测试科技有限公司",
                    "primary_score": 0.41,
                    "primary_kind": "round_stamp",
                    "primary_page": 2,
                    "pages": [2],
                },
                "chunk_strategy": "semantic",
                "chunk_strategy_requested": "semantic",
                "pipeline_hash": "pipeline-v1",
            }

    fake_db = _FakeDB(
        docs_module=documents_module,
        document=_Document(),
        chunk_ranges=[(0, 60), (50, 100)],
        chunk_contents=[("Alpha chunk",), ("Beta chunk",)],
    )

    monkeypatch.setattr(document_health_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_health_module, "assert_document_acl_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_health_module, "datetime", type("_FixedDatetime", (), {"now": staticmethod(lambda _tz=None: now)}))
    monkeypatch.setattr("app.core.pipeline_versions.resolve_doc_pipeline_key", lambda *_a, **_k: "doc:pipeline-v1", raising=True)

    def _fake_score_chunk_semantic_quality(content: str, prev_token_set=None):  # noqa: ANN001, ANN202
        if content == "Alpha chunk":
            return (
                {
                    "information_density": 0.8,
                    "semantic_completeness": 0.9,
                    "self_containedness": 0.7,
                    "pronoun_ratio": 0.05,
                    "needs_review": False,
                },
                prev_token_set,
            )
        return (
            {
                "information_density": 0.2,
                "semantic_completeness": 0.3,
                "self_containedness": 0.4,
                "pronoun_ratio": 0.15,
                "needs_review": True,
            },
            prev_token_set,
        )

    monkeypatch.setattr(
        "app.rag.chunking.quality_scorer.score_chunk_semantic_quality",
        _fake_score_chunk_semantic_quality,
        raising=True,
    )
    monkeypatch.setattr(
        "app.rag.kg.quality.kg_completeness_scorer.build_kg_quality_report",
        lambda *_a, **_k: {"summary": {"entities": 2, "relations": 1, "events": 0}},
        raising=True,
    )

    hit_calls: dict[str, object] = {}

    def _fake_compute_document_retrieval_hit_frequency(**kwargs):  # noqa: ANN202
        hit_calls.update(kwargs)
        return {
            "enabled": True,
            "available": True,
            "path": "./logs/rag_metrics.jsonl",
            "window_minutes": int(kwargs["window_minutes"]),
            "max_bytes": int(kwargs["max_bytes"]),
            "truncated": False,
            "traces_scanned": 4,
            "traces_with_hits": 2,
            "citations_matched": 3,
            "unique_chunks_matched": 2,
            "hit_rate": 0.5,
        }

    monkeypatch.setattr(
        "app.services.document_retrieval_hit_frequency.compute_document_retrieval_hit_frequency",
        _fake_compute_document_retrieval_hit_frequency,
        raising=True,
    )

    def _override_get_db():  # noqa: ANN202
        yield fake_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(documents_module.router, prefix="/api/v1/documents")
    client = TestClient(app)

    res = client.get(
        f"/api/v1/documents/{document_id}/health",
        params={"window_minutes": 1440, "max_bytes": 1234, "max_chunks_scored": 2},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["document_id"] == str(document_id)
    assert body["filename"] == "demo.pdf"
    assert body["parsing"]["parser_backend"] == "docling"
    assert body["parsing"]["is_scanned"] is True
    assert body["parsing"]["seal_summary"]["primary_text"] == "杭州测试科技有限公司"
    assert body["parsing"]["seal_summary"]["primary_score"] == 0.41
    assert body["chunking"]["chunk_count"] == 2
    assert body["chunking"]["coverage"]["covered_chars"] == 100
    assert body["chunking"]["semantic_quality"]["sampled_chunks"] == 2
    assert body["chunking"]["semantic_quality"]["needs_review"] == 1
    assert body["chunking"]["semantic_quality"]["needs_review_ratio"] == 0.5
    assert body["chunking"]["semantic_quality"]["mean_information_density"] == 0.5
    assert body["kg"]["summary"]["entities"] == 2
    assert body["retrieval_hits"]["traces_scanned"] == 4
    assert body["retrieval_hits"]["hit_rate"] == 0.5
    assert body["generated_at"] == "2026-01-02T03:04:05Z"

    assert hit_calls["tenant_id"] == tenant_id
    assert hit_calls["document_id"] == document_id
    assert hit_calls["window_minutes"] == 1440
    assert hit_calls["max_bytes"] == 1234
    assert hit_calls["now"] == now
