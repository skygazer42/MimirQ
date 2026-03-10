from __future__ import annotations

import uuid
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def test_rebuild_persisted_retrieval_indexes_writes_sparse_and_colbert_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", str(tmp_path / "sparse"), raising=False)

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", str(tmp_path / "colbert"), raising=False)

    tenant_id = _mk_uuid("tenant:rebuild")
    dataset_id = _mk_uuid("dataset:rebuild")
    doc_id = _mk_uuid("doc:rebuild")
    d1_id = _mk_uuid("chunk:rebuild:1")
    d2_id = _mk_uuid("chunk:rebuild:2")

    docs = [
        Document(
            page_content="alpha",
            id=str(d1_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(d1_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "rebuild.md",
            },
        ),
        Document(
            page_content="beta",
            id=str(d2_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 1,
                "chunk_id": str(d2_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "rebuild.md",
            },
        ),
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    monkeypatch.setattr(
        retriever,
        "_load_retrieval_docs_from_db",
        lambda *_a, **_k: list(docs),
        raising=True,
    )

    result = retriever.rebuild_persisted_retrieval_indexes(
        object(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
    )

    assert result["doc_count"] == 2
    assert result["bm25_rebuilt"] is True
    assert result["sparse_rebuilt"] is True
    assert result["colbert_rebuilt"] is True
    assert list((tmp_path / "sparse").rglob("*")), "expected persisted sparse artifacts"
    assert list((tmp_path / "colbert").rglob("*")), "expected persisted colbert artifacts"
