
import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.evaluation.evidence_retrieve_gate import build_retrieval_gate_summary, compute_retrieval_item_meta
from app.rag.retriever import HybridRetriever
from app.services.dataset_embedding_config import resolve_dataset_embedding_runtime


def _mk_uuid(name: str) -> UUID:
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
        "source": "evidence_gate",
    }
    return Document(page_content=content, id=str(chunk_id), metadata=meta)


def test_evidence_api_offline_regression_gate_hit_at_20_and_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    CI Gate: ensure Evidence API retrieval-orchestrator behavior does not regress.

    This test is deterministic + offline:
    - No vector store
    - No lexical DB (Postgres)
    - Uses in-memory BM25 via HybridRetriever
    - Calls the Evidence API retrieval orchestrator (`run_retrieval`) and evaluates
      retrieval-only metrics vs human-verified reference_sources.
    """

    # Disable features that would pull in LLMs or additional infra.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)

    # Keep the gate fully offline even if a future change triggers vector fallbacks.
    import app.rag.retriever as retriever_mod

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    tenant_id = _mk_uuid("tenant:evidence_gate")
    dataset_id = _mk_uuid("dataset:evidence_gate")
    account_id = "ci-bot"

    doc_a = _mk_uuid("doc:a")
    doc_b = _mk_uuid("doc:b")
    doc_c = _mk_uuid("doc:c")

    chunks: list[Document] = []
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_a,
            chunk_index=0,
            content="HTTP 429 Too Many Requests. Respect the Retry-After header to back off.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_b,
            chunk_index=0,
            content="Diagnostics: propagate X-Request-ID and include it in logs for cross-service tracing.",
        )
    )
    chunks.append(
        _mk_chunk(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=doc_c,
            chunk_index=0,
            content="中文: 量子纠缠是量子力学中的重要概念。检索需要支持中文分词。",
        )
    )
    # Distractors (keep corpus > top_k so hit@k is meaningful).
    for i in range(1, 40):
        chunks.append(
            _mk_chunk(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=doc_a,
                chunk_index=i,
                content=f"Noise {i}: background info about APIs, retries, headers, and timeouts.",
            )
        )

    # Seed BM25 into a retriever instance and inject it into the orchestrator module.
    import app.rag.retrieval.orchestrator as orch_mod

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    retriever.upsert_bm25_documents(chunks, tenant_id=tenant_id)
    fixture_runtime = resolve_dataset_embedding_runtime(None)
    monkeypatch.setattr(
        retriever,
        "_resolve_dataset_runtime_shards",
        lambda *, tenant_id, dataset_ids=None: [(fixture_runtime, tuple(dataset_ids or (dataset_id,)))],
        raising=False,
    )
    monkeypatch.setattr(
        retriever,
        "_resolve_embedding_runtime",
        lambda *, tenant_id: fixture_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        retriever,
        "_enrich_results_with_db_metadata",
        lambda results, **_kwargs: results,
        raising=False,
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    def _ref(chunk: Document) -> dict:
        m = chunk.metadata or {}
        return {
            "chunk_id": str(chunk.id),
            "doc_pipeline_key": m.get("doc_pipeline_key"),
            "chunk_index": m.get("chunk_index"),
            "quote": chunk.page_content,
            "label": "evidence_gate",
        }

    cases = [
        {"question": "429 Retry-After header", "reference_sources": [_ref(chunks[0])]},
        {"question": "X-Request-ID tracing", "reference_sources": [_ref(chunks[1])]},
        {"question": "量子纠缠", "reference_sources": [_ref(chunks[2])]},
    ]

    metas: list[dict] = []
    for case in cases:
        out = orch_mod.run_retrieval(
            {
                "question": str(case["question"]),
                "history": [],
                "tenant_id": tenant_id,
                "account_id": account_id,
                "dataset_id": dataset_id,
                "document_ids": [],
                "top_k": 20,
                "score_threshold": 0.0,
                "retrieval_mode": "keyword",
                "metrics": {},
            }
        )
        citations = out.get("citations") or []
        metas.append(compute_retrieval_item_meta(case=case, citations=citations))

    summary = build_retrieval_gate_summary(metas)

    # SLO: deterministic small corpus should be perfect.
    assert summary["retrieval_hit_at_20"] == pytest.approx(1.0)
    assert summary["retrieval_recall"] == pytest.approx(1.0)
    assert summary["must_recall_pass_rate"] == pytest.approx(1.0)
    assert summary["must_recall_cases_total"] == 3
    assert summary["must_recall_cases_failed"] == 0
