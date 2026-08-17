from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentChunk, DocumentParsedContent, DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services import chat_tag_service, dataset_precheck_service, document_qa_service
from app.services.document_access import get_allowed_document_id_sets, list_accessible_document_ids


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(
    _type: object,
    _compiler: object,
    **_kwargs: object,
) -> str:
    return "JSON"


def _open_session(*tables) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=list(tables))
    return Session(engine)


def test_extract_qa_pairs_preserves_multiline_answers_and_pair_limit() -> None:
    text = (
        "Q: First question?\n"
        "A: first line\n"
        "still first\n"
        "Q: Second question?\n"
        "A: second line\n"
        "Q: Third question?\n"
        "A: third line\n"
    )

    pairs = document_qa_service.extract_qa_pairs_from_text(text, max_pairs=2)

    assert pairs == [
        document_qa_service.QAPair(question="First question?", answer="first line\nstill first"),
        document_qa_service.QAPair(question="Second question?", answer="second line"),
    ]


def test_generate_and_index_document_qa_replaces_active_qa_chunks_and_updates_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _open_session(
        Dataset.__table__,
        Document.__table__,
        DocumentChunk.__table__,
        DocumentParsedContent.__table__,
    )

    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    active_hash = "pipeline-v1"
    active_key = f"{document_id}:{active_hash}"

    dataset = Dataset(
        id=dataset_id,
        tenant_id=tenant_id,
        name="QA Dataset",
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner-1",
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="guide.pdf",
        file_type="pdf",
        file_size=128,
        file_path="/tmp/guide.pdf",
        owner_id="owner-1",
        access_mode="inherit",
        publication_status="published",
        status="completed",
        chunk_count=0,
        total_characters=0,
        doc_metadata={"active_pipeline_hash": active_hash},
    )
    parsed = DocumentParsedContent(
        tenant_id=tenant_id,
        document_id=document_id,
        markdown_content="Q: Alpha?\nA: One\nQ: Beta?\nA: Two",
    )
    removable = DocumentChunk(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=0,
        content="legacy qa",
        doc_metadata={"doc_pipeline_key": active_key, "file_type": "qa"},
    )
    preserved = DocumentChunk(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=1,
        content="keep me",
        doc_metadata={"doc_pipeline_key": "other-pipeline", "file_type": "qa"},
    )
    db.add_all([dataset, document, parsed, removable, preserved])
    db.commit()

    deleted_filters: list[dict[str, object]] = []
    bm25_updates: list[list[UUID]] = []

    class _VectorStore:
        def add_documents(
            self,
            records: list[dict[str, object]],
            _document_id: UUID,
            _tenant_id: UUID,
        ) -> list[str]:
            return [f"vec-{index}" for index, _ in enumerate(records)]

        def delete_by_document_id_and_filter(self, **kwargs: object) -> None:
            deleted_filters.append(kwargs)

    monkeypatch.setattr(document_qa_service, "get_vector_store", lambda: _VectorStore(), raising=True)
    monkeypatch.setattr(
        document_qa_service,
        "hybrid_retriever",
        SimpleNamespace(remove_from_bm25_index_by_metadata_filter=lambda **_kwargs: None),
        raising=True,
    )
    monkeypatch.setattr(
        document_qa_service.Indexer,
        "_update_bm25_for_chunks",
        lambda _self, *, db_chunks, **_kwargs: bm25_updates.append([chunk.id for chunk in db_chunks]),
        raising=True,
    )

    result = document_qa_service.generate_and_index_document_qa(
        db,
        tenant_id=tenant_id,
        document=document,
        num_pairs=2,
        replace_existing=True,
        prefer_llm=False,
    )

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.content.asc())
        .all()
    )
    qa_rows = [row for row in rows if row.doc_metadata.get("doc_pipeline_key") == active_key]

    assert result.mode == "extract"
    assert result.deleted == 1
    assert result.created == 2
    assert result.preview == [
        {"question": "Alpha?", "answer": "One"},
        {"question": "Beta?", "answer": "Two"},
    ]
    assert len(deleted_filters) == 1
    assert bm25_updates == [[chunk.id for chunk in qa_rows]]
    assert preserved.id in {row.id for row in rows}
    assert [row.content for row in qa_rows] == ["Q: Alpha?\nA: One", "Q: Beta?\nA: Two"]
    assert all(row.vector_id for row in qa_rows)
    assert all(row.doc_metadata["file_type"] == "qa" for row in qa_rows)
    assert all(row.doc_metadata["doc_pipeline_key"] == active_key for row in qa_rows)
    assert all(row.doc_metadata["pipeline_hash"] == active_hash for row in qa_rows)
    assert document.chunk_count == 2
    assert document.total_characters == sum(len(row.content) for row in qa_rows)

    db.close()


def test_document_access_preserves_tenant_scope_group_acl_and_active_pipeline_ready() -> None:
    db = _open_session(
        Tenant.__table__,
        TenantMember.__table__,
        TenantGroup.__table__,
        TenantGroupMember.__table__,
        Dataset.__table__,
        DatasetPermission.__table__,
        DatasetGroupPermission.__table__,
        Document.__table__,
        DocumentPermission.__table__,
        DocumentGroupPermission.__table__,
    )

    tenant_id = uuid4()
    foreign_tenant_id = uuid4()
    group_id = uuid4()
    dataset_id = uuid4()
    partial_doc_id = uuid4()
    ready_doc_id = uuid4()
    legacy_doc_id = uuid4()
    foreign_doc_id = uuid4()
    account_id = "group-reader"

    db.add_all(
        [
            Tenant(id=tenant_id, name="tenant-a"),
            Tenant(id=foreign_tenant_id, name="tenant-b"),
            TenantMember(
                tenant_id=tenant_id,
                user_id=account_id,
                role="viewer",
                is_active=True,
                is_current=True,
            ),
            TenantGroup(id=group_id, tenant_id=tenant_id, name="readers"),
            TenantGroupMember(tenant_id=tenant_id, group_id=group_id, user_id=account_id),
            Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name="Scoped Dataset",
                permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
                owner_id="dataset-owner",
            ),
            DatasetGroupPermission(tenant_id=tenant_id, dataset_id=dataset_id, group_id=group_id),
            Document(
                id=partial_doc_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                filename="partial.pdf",
                file_type="pdf",
                file_size=1,
                file_path="/tmp/partial.pdf",
                owner_id="other-owner",
                access_mode="partial_members",
                publication_status="published",
                status="completed",
                chunk_count=1,
                total_characters=10,
                doc_metadata={},
            ),
            Document(
                id=ready_doc_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                filename="ready.pdf",
                file_type="pdf",
                file_size=1,
                file_path="/tmp/ready.pdf",
                owner_id="other-owner",
                access_mode=None,
                publication_status="published",
                status="processing",
                chunk_count=1,
                total_characters=10,
                doc_metadata={"active_pipeline_ready": "true"},
            ),
            Document(
                id=legacy_doc_id,
                tenant_id=tenant_id,
                dataset_id=None,
                filename="legacy.pdf",
                file_type="pdf",
                file_size=1,
                file_path="/tmp/legacy.pdf",
                owner_id="other-owner",
                access_mode="inherit",
                publication_status="published",
                status="completed",
                chunk_count=1,
                total_characters=10,
                doc_metadata={},
            ),
            Document(
                id=foreign_doc_id,
                tenant_id=foreign_tenant_id,
                dataset_id=None,
                filename="foreign.pdf",
                file_type="pdf",
                file_size=1,
                file_path="/tmp/foreign.pdf",
                owner_id="other-owner",
                access_mode="all_team_members",
                publication_status="published",
                status="completed",
                chunk_count=1,
                total_characters=10,
                doc_metadata={},
            ),
            DocumentGroupPermission(tenant_id=tenant_id, document_id=partial_doc_id, group_id=group_id),
        ]
    )
    db.commit()

    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        [partial_doc_id, ready_doc_id, legacy_doc_id, foreign_doc_id],
    )
    accessible_ids = list_accessible_document_ids(
        db,
        tenant_id,
        account_id,
        status="completed",
        limit=None,
    )

    assert allowed_ids == {partial_doc_id, ready_doc_id}
    assert missing_ids == {foreign_doc_id}
    assert set(accessible_ids) == {partial_doc_id, ready_doc_id}

    db.close()


def test_precheck_sample_reviews_and_near_dup_listing_preserve_review_and_cluster_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    scan_run_id = uuid4()
    artifacts_dir = tmp_path / str(tenant_id) / "precheck" / str(scan_run_id)
    artifacts_dir.mkdir(parents=True)

    files_jsonl = artifacts_dir / "files.jsonl"
    near_dups_json = artifacts_dir / "near_dups.json"
    files_jsonl.write_text(
        "\n".join(
            [
                json.dumps({"name": "alpha.pdf", "file_type": "pdf", "file_size": 10, "findings": ["near_dup"]}),
                json.dumps({"name": "beta.pdf", "file_type": "pdf", "file_size": 20, "findings": []}),
                json.dumps({"name": "gamma.pdf", "file_type": "pdf", "file_size": 30, "findings": ["near_dup"]}),
            ]
        ),
        encoding="utf-8",
    )
    near_dups_json.write_text(
        json.dumps({"clusters": [{"members": ["alpha.pdf", "gamma.pdf"]}, {"members": ["missing.pdf"]}]}),
        encoding="utf-8",
    )

    row = SimpleNamespace(
        id=scan_run_id,
        artifacts={
            "files_jsonl": str(files_jsonl),
            "near_dups_json": str(near_dups_json),
        },
    )
    monkeypatch.setattr(dataset_precheck_service.settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    review = dataset_precheck_service.upsert_precheck_sample_review_for_row(
        row,
        tenant_id=tenant_id,
        account_id="reviewer-1",
        file_name="alpha.pdf",
        disposition="keep",
    )
    reviews = dataset_precheck_service.load_precheck_sample_reviews_from_row(row, tenant_id=tenant_id)
    merged = dataset_precheck_service.apply_precheck_sample_reviews(
        {
            "representative": [{"name": "alpha.pdf"}, {"name": "beta.pdf"}],
            "needs_review": {"near_dup": [{"name": "alpha.pdf"}, {"name": "gamma.pdf"}]},
        },
        reviews,
    )
    near_dup_files = dataset_precheck_service.list_near_dup_files_from_row(
        row,
        tenant_id=tenant_id,
        skip=0,
        limit=10,
    )

    assert row.artifacts["sample_reviews_json"].endswith("sample_reviews.json")
    assert review["review_disposition"] == "keep"
    assert review["reviewed_by"] == "reviewer-1"
    assert reviews["alpha.pdf"]["review_disposition"] == "keep"
    assert merged["representative"][0]["review_disposition"] == "keep"
    assert merged["needs_review"]["near_dup"][0]["reviewed_by"] == "reviewer-1"
    assert "review_disposition" not in merged["representative"][1]
    assert near_dup_files.total == 2
    assert [item.name for item in near_dup_files.items] == ["alpha.pdf", "gamma.pdf"]


def test_chat_tag_context_docs_match_quoted_source_keys_and_row_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    captured_sql: list[str] = []

    class _FakeQuery:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def filter(self, *_args, **_kwargs) -> _FakeQuery:
            return self

        def all(self) -> list[object]:
            return list(self._rows)

    class _FakeDB:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def query(self, *_args, **_kwargs) -> _FakeQuery:
            return _FakeQuery(self._rows)

    doc = SimpleNamespace(
        id=document_id,
        dataset_id=dataset_id,
        filename="Policy Q1.csv",
        file_type="dbrows",
        status="completed",
        doc_metadata={
            "table_store": {
                "source_ext": ".dbrows",
                "tables": [
                    {
                        "table_id": "policy_q1",
                        "sheet_index": 0,
                        "sheet_name": "Policy Q1",
                        "row_count": 3,
                        "col_count": 2,
                        "columns": [{"name": "policy_name"}, {"name": "__row_pk_hash"}],
                        "sample_rows": [{"policy_name": "Revenue", "__row_pk_hash": "pk-1"}],
                        "row_source_table": "warehouse.policy_q1",
                        "row_source_sync_token": "sync-1",
                        "row_source_pk_hash_col": "__row_pk_hash",
                    }
                ],
            }
        },
    )

    monkeypatch.setattr(chat_tag_service.settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_tag_service.settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_tag_service.settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(chat_tag_service.settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(chat_tag_service.settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", True, raising=False)
    monkeypatch.setattr(
        chat_tag_service.settings,
        "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(chat_tag_service.settings, "CHAT_TAG_MAX_TABLES", 1, raising=False)
    monkeypatch.setattr(
        chat_tag_service,
        "generate_sql_for_table_with_metadata",
        lambda **_kwargs: (
            "select policy_name, __row_pk_hash from sheet_0 limit 5",
            "deterministic",
            {
                "schema_link": {"score": 0.9, "strategy": "deterministic", "reason": "matched"},
                "planner": {"strategy": "deterministic", "sql_fingerprint": "fp-1"},
            },
        ),
        raising=True,
    )

    def _run_table_query(**kwargs: object) -> dict[str, object]:
        captured_sql.append(str(kwargs["sql"]))
        return {
            "sql": kwargs["sql"],
            "columns": ["policy_name", "__row_pk_hash"],
            "rows": [["Revenue", "pk-1"]],
            "truncated": False,
        }

    monkeypatch.setattr(chat_tag_service, "run_table_query", _run_table_query, raising=True)

    docs, meta = chat_tag_service.build_chat_tag_context_docs(
        _FakeDB([doc]),
        tenant_id=tenant_id,
        document_ids=[document_id],
        question="筛选 Policy Q1 里的 Revenue",
        must_recall_expected_source_keys=["'Policy Q1'"],
    )

    payload = json.loads(docs[0].page_content)

    assert captured_sql == ["select policy_name, __row_pk_hash from sheet_0 limit 5"]
    assert meta["used"] is True
    assert meta["must_recall_expected_source_keys"] == ["'Policy Q1'"]
    assert payload["must_recall_source_key_match"] is True
    assert payload["must_recall_expected_source_keys"] == ["'Policy Q1'"]
    assert payload["row_source"] == {
        "table": "warehouse.policy_q1",
        "sync_token": "sync-1",
        "pk_hashes": ["pk-1"],
    }
    assert docs[0].metadata["row_source_table"] == "warehouse.policy_q1"
    assert docs[0].metadata["row_source_pk_hashes"] == ["pk-1"]
