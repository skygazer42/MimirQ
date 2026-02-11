from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.evaluation.ragas import _build_regression_gate_summary  # noqa: SLF001
from app.rag.evaluation.regression_sample_builder import build_regression_sample
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    # Stable IDs make this test a true regression gate (no snapshot churn).
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def _mk_chunk(  # noqa: PLR0913
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    chunk_index: int,
    content: str,
    pipeline_hash: str = "h",
) -> Document:
    chunk_id = _mk_uuid(f"chunk:{document_id}:{chunk_index}")
    doc_pipeline_key = f"{document_id}:{pipeline_hash}"
    meta = {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document_id),
        "chunk_index": int(chunk_index),
        "chunk_id": str(chunk_id),
        "doc_pipeline_key": doc_pipeline_key,
        "pipeline_hash": pipeline_hash,
        "source": "retrieval_gate",
    }
    return Document(page_content=content, id=str(chunk_id), metadata=meta)


def test_retrieval_regression_slo_gate_hit_at_20_and_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    CI Gate: ensure retrieval-only quality SLOs do not regress.

    This is intentionally deterministic + offline:
    - Uses in-memory BM25 (no vector store, no DB).
    - Uses the same regression-case metrics as the production RAGAS regression runs
      (hit@k / recall / MRR / NDCG derived from reference_sources vs citations).
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False)

    # Keep the gate fully offline even if a future change triggers vector fallbacks.
    import app.rag.retriever as retriever_mod

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    tenant_id = _mk_uuid("tenant:retrieval_gate")
    dataset_id = _mk_uuid("dataset:retrieval_gate")

    doc_a = _mk_uuid("doc:a")
    doc_b = _mk_uuid("doc:b")
    doc_c = _mk_uuid("doc:c")
    doc_d = _mk_uuid("doc:d")
    doc_e = _mk_uuid("doc:e")

    chunks: list[Document] = []
    # High-signal target chunks (evidence).
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_a,
            chunk_index=0,
            content="HTTP 429 Too Many Requests. Clients should respect the Retry-After header to back off.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_a,
            chunk_index=1,
            content="Diagnostics: propagate X-Request-ID and include it in logs for cross-service tracing.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_b,
            chunk_index=0,
            content="Release notes: v1.2.3 fixes dataset-scoped retrieval filter injection and improves recall@20.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_b,
            chunk_index=1,
            content="Compatibility: Python 3.10.0 is supported. Prefer 3.10 for stable typing behavior.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_c,
            chunk_index=0,
            content="Numeric formats: accept 12_345 and 1,234 as user inputs and normalize to 12345 / 1234.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_d,
            chunk_index=0,
            content="中文: 量子纠缠是量子力学中的重要概念。检索需要支持中文分词与 OOV bigram 兜底。",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_e,
            chunk_index=0,
            content="API endpoints: POST /api/v1/rag/retrieve (evidence-only) and POST /api/v1/rag/retrieve-preview (debug).",
        )
    )

    # Add distractors (keep corpus > top_k to make hit@k meaningful).
    for i in range(2, 30):
        chunks.append(
            _mk_chunk(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=doc_a,
                chunk_index=i,
                content=f"Noise A{i}: background info about APIs, retries, and headers. Nothing about evidence chunk {i}.",
            )
        )
    for i in range(2, 30):
        chunks.append(
            _mk_chunk(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=doc_b,
                chunk_index=i,
                content=f"Noise B{i}: changelog entry with various unrelated tokens and versions like v0.{i}.0.",
            )
        )
    for i in range(1, 25):
        chunks.append(
            _mk_chunk(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=doc_c,
                chunk_index=i,
                content=f"Noise C{i}: numbers 10{i}, 20{i}, 30{i} and text that should not outrank the normalization chunk.",
            )
        )

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(chunks, tenant_id=tenant_id)

    def _ref(chunk: Document) -> dict:
        m = chunk.metadata or {}
        return {
            "chunk_id": str(chunk.id),
            "doc_pipeline_key": m.get("doc_pipeline_key"),
            "chunk_index": m.get("chunk_index"),
            "quote": chunk.page_content,
            "label": "retrieval_gate",
        }

    # Regression cases: each is a retrieval-only question with human-verified evidence pointers.
    cases = [
        {"question": "429 Retry-After header", "reference_sources": [_ref(chunks[0])]},
        {"question": "X-Request-ID tracing", "reference_sources": [_ref(chunks[1])]},
        {"question": "v1.2.3 dataset scoped retrieval", "reference_sources": [_ref(chunks[2])]},
        {"question": "Python 3.10 support", "reference_sources": [_ref(chunks[3])]},
        {"question": "normalize 12_345 to 12345", "reference_sources": [_ref(chunks[4])]},
        {"question": "1,234 normalization", "reference_sources": [_ref(chunks[4])]},
        {"question": "量子纠缠", "reference_sources": [_ref(chunks[5])]},
        {"question": "POST /api/v1/rag/retrieve-preview", "reference_sources": [_ref(chunks[6])]},
    ]

    eval_items: list[dict] = []
    for case in cases:
        query = str(case.get("question") or "")
        results = retriever._hybrid_search(
            query=query,
            top_k=20,
            score_threshold=0.0,
            document_ids=None,
            tenant_id=tenant_id,
            retrieval_mode="keyword",
            metadata_filter=None,
        )
        citations = []
        contexts = []
        for r in results:
            meta = r.get("metadata") or {}
            citations.append(
                {
                    "chunk_id": r.get("chunk_id"),
                    "doc_pipeline_key": meta.get("doc_pipeline_key"),
                    "chunk_index": meta.get("chunk_index"),
                    "chunk_content": r.get("content"),
                }
            )
            contexts.append(r.get("content") or "")

        _sample_kwargs, item_meta = build_regression_sample(  # noqa: SLF001
            case,
            {
                "question": query,
                "response": "",
                "retrieved_contexts": contexts,
                "citations": citations,
                "abstain_triggered": False,
            },
        )
        eval_items.append({"item_meta": item_meta})

    summary = _build_regression_gate_summary(eval_items)  # noqa: SLF001

    # SLO baselines (per dataset): keep these strict to prevent silent recall regressions.
    assert summary.get("retrieval_hit_at_20") == 1.0
    assert summary.get("retrieval_recall") == 1.0
