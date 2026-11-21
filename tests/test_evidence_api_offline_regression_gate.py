import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.hashing import stable_json_hash
from app.rag.evaluation.regression.evidence_retrieve_gate import (
    build_retrieval_gate_summary,
    compute_retrieval_item_meta,
)
from app.rag.retrieval.corpus import CorpusIndex
from app.rag.retrieval.evidence.capsule import validate_evidence_capsule
from app.rag.retrieval.recall.retriever import HybridRetriever
from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope, RuntimeShard
from app.services.datasets.embedding_config import resolve_dataset_embedding_runtime


@pytest.fixture(autouse=True)
def _offline_stream_models(monkeypatch):
    from app.infrastructure import tokens

    monkeypatch.setattr(tokens, "_get_encoder", lambda: False)


class _CorpusStore:
    def __init__(self):
        self.documents = []

    def upsert(self, documents, *, tenant_id):
        assert all(document.metadata["tenant_id"] == str(tenant_id) for document in documents)
        self.documents = list(documents)

    def search(self, query, *, tenant_id, dataset_ids, document_ids, metadata_filter, top_k):
        assert metadata_filter is None
        records = []
        for document in self.documents:
            metadata = document.metadata
            if metadata["tenant_id"] != str(tenant_id):
                continue
            if dataset_ids and metadata["dataset_id"] not in {str(value) for value in dataset_ids}:
                continue
            if document_ids and metadata["document_id"] not in {str(value) for value in document_ids}:
                continue
            score = sum(term in document.page_content.casefold() for term in query.casefold().split())
            if score:
                records.append(
                    {
                        "chunk_id": str(document.id),
                        "content": document.page_content,
                        "score": float(score),
                        "metadata": dict(metadata),
                    }
                )
        return sorted(records, key=lambda record: record["score"], reverse=True)[:top_k]


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
    - Uses the current CorpusIndex channel with an explicit local store fixture
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
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", False)

    # Keep the gate fully offline even if a future change triggers vector fallbacks.
    import app.rag.retrieval.recall.retriever as retriever_mod

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr("app.rag.retrieval.recall.channel_collection.get_vector_store", lambda: _StubVectorStore())

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
    corpus = CorpusIndex(bm25_store=_CorpusStore())
    corpus.upsert(None, tenant_id=tenant_id, documents=chunks)
    monkeypatch.setattr(retriever_mod, "get_corpus_index", lambda: corpus)
    monkeypatch.setattr(corpus, "resolve_version", lambda _scope, **_kwargs: "fixture-corpus")
    fixture_runtime = resolve_dataset_embedding_runtime(None)
    monkeypatch.setattr(
        retriever,
        "_resolve_hybrid_runtime_scope",
        lambda **_kwargs: ResolvedRetrievalScope(
            RetrievalScope(tenant_id, account_id, dataset_ids=(dataset_id,)),
            (dataset_id,),
            (RuntimeShard(fixture_runtime, (dataset_id,)),),
            fixture_runtime,
            None,
            None,
            None,
            False,
        ),
    )
    monkeypatch.setattr(
        retriever,
        "_enrich_results_with_db_metadata",
        lambda results, **_kwargs: results,
        raising=False,
    )
    monkeypatch.setattr("app.rag.retrieval.stages.preparation.hybrid_retriever", retriever, raising=True)
    monkeypatch.setattr("app.rag.retrieval.stages.followup.hybrid_retriever", retriever, raising=True)
    monkeypatch.setattr("app.rag.retrieval.stages.requirements.hybrid_retriever", retriever, raising=True)

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
                "intent_router": False,
                "adaptive_router": False,
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


def test_compute_retrieval_item_meta_builds_valid_provenance_capsule() -> None:
    case = {
        "question": "retry header",
        "reference_sources": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "doc_pipeline_key": "doc-1:pipeline-a",
                "chunk_index": 0,
                "quote": "Retry-After header guidance",
            }
        ],
    }
    citations = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "doc_pipeline_key": "doc-1:pipeline-a",
            "chunk_index": 0,
            "quote": "Retry-After header guidance",
            "retrieval_role": "main",
            "hit_type": "keyword",
        }
    ]

    meta = compute_retrieval_item_meta(case=case, citations=citations, retrieval_metrics={"retrieval_mode": "keyword"})
    summary = build_retrieval_gate_summary([meta])

    assert meta["must_recall_passed"] is True
    assert meta["must_recall_status"] == "passed"
    assert meta["provenance_integrity_passed"] is True
    assert meta["provenance_integrity_status"] == "passed"
    assert isinstance(meta["evidence_capsule"], dict)
    assert meta["evidence_capsule"]["must_recall"]["passed"] is True
    assert meta["evidence_capsule"]["must_recall"]["status"] == "passed"
    assert summary["total_cases"] == 1
    assert summary["must_recall_pass_rate"] == pytest.approx(1.0)
    assert summary["must_recall_passed_cases"] == 1
    assert summary["provenance_integrity_rate"] == pytest.approx(1.0)
    assert summary["provenance_passed_cases"] == 1


def test_compute_retrieval_item_meta_rehashes_sanitized_upstream_citation() -> None:
    case = {
        "question": "retry header",
        "reference_sources": [{"chunk_id": "chunk-1", "document_id": "doc-1"}],
    }
    citation = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "chunk_content": "Retry-After header guidance",
        "evidence_anchor_hash": "anchor-1",
        "retrieval_role": "main",
        "hit_type": "keyword",
    }
    citation["citation_hash"] = stable_json_hash(citation, length=16)
    upstream_hash = citation["citation_hash"]

    meta = compute_retrieval_item_meta(
        case=case,
        citations=[citation],
        retrieval_metrics={"retrieval_mode": "keyword"},
    )

    capsule = meta["evidence_capsule"]
    capsule_citation = capsule["citations"][0]
    assert capsule_citation["source_citation_hash"] == upstream_hash
    assert capsule_citation["citation_hash"] != upstream_hash
    assert validate_evidence_capsule(capsule, strict=True, verify_signature=False) == (True, "ok")
    assert meta["provenance_integrity_passed"] is True


def test_compute_retrieval_item_meta_marks_invalid_provenance_capsule_failed() -> None:
    case = {
        "question": "retry header",
        "reference_sources": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "doc_pipeline_key": "doc-1:pipeline-a",
                "chunk_index": 0,
                "quote": "Retry-After header guidance",
            }
        ],
    }
    citations = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "doc_pipeline_key": "doc-1:pipeline-a",
            "chunk_index": 0,
            "quote": "Retry-After header guidance",
        }
    ]

    meta = compute_retrieval_item_meta(
        case=case,
        citations=citations,
        retrieval_metrics={"evidence_capsule": {"schema": "mimirq.evidence_capsule.v1", "citations": []}},
    )

    assert meta["must_recall_passed"] is True
    assert meta["provenance_integrity_passed"] is False
    assert meta["provenance_integrity_status"] == "failed"


def test_compute_retrieval_item_meta_preserves_explicit_base_must_recall_result() -> None:
    meta = compute_retrieval_item_meta(
        case={"question": "already evaluated"},
        citations=[],
        base_meta={"must_recall_passed": False, "retrieval_recall": 1.0},
    )

    assert meta["must_recall_passed"] is False
    assert meta["must_recall_status"] == "failed"


def test_ragas_regression_gate_summary_includes_must_recall_and_provenance() -> None:
    from app.rag.evaluation.regression.ragas import _build_regression_gate_summary

    case = {
        "question": "retry header",
        "reference_sources": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "doc_pipeline_key": "doc-1:pipeline-a",
                "chunk_index": 0,
                "quote": "Retry-After header guidance",
            }
        ],
    }
    citations = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "doc_pipeline_key": "doc-1:pipeline-a",
            "chunk_index": 0,
            "quote": "Retry-After header guidance",
            "retrieval_role": "main",
            "hit_type": "keyword",
        }
    ]
    item_meta = compute_retrieval_item_meta(
        case=case, citations=citations, retrieval_metrics={"retrieval_mode": "keyword"}
    )

    summary = _build_regression_gate_summary([{"item_meta": item_meta}])

    assert summary["must_recall_pass_rate"] == pytest.approx(1.0)
    assert summary["must_recall_passed_cases"] == 1
    assert summary["provenance_integrity_rate"] == pytest.approx(1.0)
    assert summary["provenance_passed_cases"] == 1
