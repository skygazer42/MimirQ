from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


def _mk_doc(*, chunk_id: str, document_id: str, text: str, tenant_id: uuid.UUID, dataset_id: uuid.UUID) -> Document:
    return Document(
        page_content=text,
        id=chunk_id,
        metadata={
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": document_id,
            "chunk_id": chunk_id,
            "pipeline_hash": "ml-regression-v1",
            "doc_pipeline_key": f"{document_id}:ml-regression-v1",
            "source": f"{document_id}.md",
            "chunk_index": 0,
        },
    )


def _ranked_ids(*, retriever, tenant_id: uuid.UUID, query: str, top_k: int = 3) -> list[str]:
    rows = retriever._hybrid_search(  # noqa: SLF001
        query=query,
        top_k=top_k,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        metadata_filter=None,
    )
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("chunk_id") or "").strip()
        if cid:
            out.append(cid)
    return out[:top_k]


def test_multilingual_tokenization_normalizes_fullwidth_ascii_and_digits() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("ＡＰＩ v２ ２０２６")
    assert "api" in tokens
    assert "v2" in tokens
    assert "2026" in tokens


@pytest.mark.filterwarnings("ignore:The pynvml package is deprecated")
def test_multilingual_recall_regression_mixed_queries_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    # Keep retrieval deterministic and local.
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        sparse_enabled=False,
        sparse_provider="deterministic",
    )

    docs = [
        _mk_doc(
            chunk_id="c-api",
            document_id="d-api",
            text="API endpoint supports refund flow and billing status checks.",
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        ),
        _mk_doc(
            chunk_id="c-zh",
            document_id="d-zh",
            text="如何配置单点登录和企业账号绑定流程。",
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        ),
        _mk_doc(
            chunk_id="c-en",
            document_id="d-en",
            text="Password reset instructions for enterprise SSO users.",
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        ),
    ]
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    cases = [
        ("ＡＰＩ", "c-api"),
        ("单点登录 配置", "c-zh"),
        ("password reset", "c-en"),
    ]
    for query, expected in cases:
        ranked = _ranked_ids(retriever=retriever, tenant_id=tenant_id, query=query, top_k=3)
        assert expected in ranked, (query, ranked)

    # Deterministic across runs for the same mixed-language query.
    first = _ranked_ids(retriever=retriever, tenant_id=tenant_id, query="ＡＰＩ", top_k=3)
    second = _ranked_ids(retriever=retriever, tenant_id=tenant_id, query="ＡＰＩ", top_k=3)
    assert first == second
