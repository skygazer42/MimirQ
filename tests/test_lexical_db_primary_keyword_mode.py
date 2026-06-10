from __future__ import annotations

from uuid import UUID, uuid4

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _lexical_hit(document_id: str, *, score: float = 0.9) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}:0",
        "content": f"lexical:{document_id}",
        "score": score,
        "metadata": {
            "document_id": document_id,
            "chunk_id": f"{document_id}:0",
            "chunk_index": 0,
            "lexical_method": "fts",
        },
        "lexical_score": score,
    }


def _bm25_hit(document_id: str, *, score: float = 7.5) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}:0",
        "content": f"bm25:{document_id}",
        "score": score,
        "metadata": {
            "document_id": document_id,
            "chunk_id": f"{document_id}:0",
            "chunk_index": 0,
        },
        "bm25_score": score,
    }


def _metadata_question_hit(document_id: str, *, question: str, score: float = 0.9) -> dict[str, object]:
    hit = _bm25_hit(document_id, score=score)
    metadata = dict(hit["metadata"])  # type: ignore[arg-type]
    metadata["question"] = question
    hit["metadata"] = metadata
    hit["content"] = f"问题：{question}\n答案：stub"
    return hit


def _metadata_service_hit(document_id: str, *, service_name: str, score: float = 0.9) -> dict[str, object]:
    hit = _bm25_hit(document_id, score=score)
    metadata = dict(hit["metadata"])  # type: ignore[arg-type]
    metadata["service_name"] = service_name
    metadata["gov_knowledge_type"] = "service_item"
    hit["metadata"] = metadata
    hit["content"] = f"事项名称：{service_name}\n咨询方式：0519-00000000"
    return hit


def test_keyword_mode_prefers_lexical_db_and_skips_bm25_by_default(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=2,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical"]
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-lexical"

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is False
    assert channels["keyword_strategy"]["lexical_db_used"] is True
    assert channels["keyword_strategy"]["bm25_used"] is False
    assert channels["lexical_db"]["candidates"] == 1
    assert channels["bm25"]["candidates"] == 0


def test_keyword_mode_can_run_bm25_as_secondary_after_lexical(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    retriever.enable_reranker = False
    calls: list[str] = []

    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=4,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical", "bm25"]
    assert {item["document_id"] for item in results} == {"doc-lexical", "doc-bm25"}

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["secondary"] == "bm25"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is True
    assert channels["keyword_strategy"]["lexical_db_used"] is True
    assert channels["keyword_strategy"]["bm25_used"] is True
    assert channels["counts"]["lexical_candidates"] == 1
    assert channels["counts"]["bm25_candidates"] == 1


def test_keyword_mode_falls_back_to_bm25_when_lexical_primary_returns_empty(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_bm25_hit("doc-vector")]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="apac review",
        top_k=2,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical", "bm25"]
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-bm25"

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is False
    assert channels["keyword_strategy"]["lexical_db_used"] is False
    assert channels["keyword_strategy"]["bm25_used"] is True
    assert channels["counts"]["lexical_candidates"] == 0
    assert channels["counts"]["bm25_candidates"] == 1
    assert channels["counts"]["vector_candidates"] == 0


def test_keyword_mode_prefers_excel_bm25_hit_over_vector_distractors_when_lexical_misses(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [
                {
                    "document_id": "doc-docx",
                    "chunk_id": "doc-docx:0",
                    "content": "Owner: Lina Chen",
                    "score": 0.9,
                    "metadata": {"document_id": "doc-docx", "chunk_id": "doc-docx:0", "chunk_index": 0},
                    "vector_score": 0.9,
                },
                {
                    "document_id": "doc-yaml",
                    "chunk_id": "doc-yaml:0",
                    "content": "token: YAML-CINDER owner: Yara Cinder status: approved",
                    "score": 0.8,
                    "metadata": {"document_id": "doc-yaml", "chunk_id": "doc-yaml:0", "chunk_index": 0},
                    "vector_score": 0.8,
                },
            ]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25")
        or [
            {
                "document_id": "doc-xlsx",
                "chunk_id": "doc-xlsx:0",
                "content": "Excel: sample.xlsx\n\n## Sheet: Budget\n\n| Region | Budget | Status |\n| APAC | 138 | Review |",
                "score": 9.0,
                "metadata": {"document_id": "doc-xlsx", "chunk_id": "doc-xlsx:0", "chunk_index": 0},
                "bm25_score": 9.0,
            },
            _bm25_hit("doc-csv", score=1.0),
        ],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="In the Excel budget sheet, what status belongs to APAC?",
        top_k=4,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical", "bm25"]
    assert [item["document_id"] for item in results] == ["doc-xlsx", "doc-csv"]

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["bm25_used"] is True
    assert channels["keyword_strategy"]["lexical_db_used"] is False
    assert channels["counts"]["vector_candidates"] == 0
    assert channels["counts"]["bm25_candidates"] == 2


def test_hybrid_mode_skips_lexical_db_when_primary_channels_are_sufficient(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_bm25_hit("doc-vector-1"), _bm25_hit("doc-vector-2")]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25-1"), _bm25_hit("doc-bm25-2")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25"]
    assert len(results) == 3

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["enabled"] is True
    assert channels["lexical_db"]["used"] is False
    assert channels["lexical_db"]["run_reason"] == "skipped_primary_candidates_sufficient"
    assert channels["timing"]["lexical_ms"] == 0.0


def test_hybrid_mode_runs_metadata_exact_fallback_for_service_intent_query(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    retriever.enable_reranker = False
    calls: list[str] = []
    query = "天宁区学区划分查询咨询电话是多少"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_metadata_service_hit("doc-vector", service_name="重名查询", score=0.68)]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(retriever, "_search_bm25", lambda **_kwargs: calls.append("bm25") or [], raising=True)
    monkeypatch.setattr(retriever, "_search_lexical_db", lambda **_kwargs: calls.append("lexical") or [], raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_metadata_exact_anchor_db",
        lambda **_kwargs: calls.append("metadata_exact")
        or [_metadata_service_hit("doc-exact", service_name="学区划分查询", score=0.99)],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=1,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical", "metadata_exact"]
    assert results[0]["document_id"] == "doc-exact"
    channels = retriever._last_channel_metrics
    assert channels["lexical_metadata_exact_fallback"]["query_anchor_like"] is True
    assert channels["lexical_metadata_exact_fallback"]["triggered"] is True
    assert channels["metadata_exact_db"]["used"] is True


def test_hybrid_metadata_exact_fallback_enriches_when_lexical_has_only_one_exact_anchor(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    retriever.enable_reranker = False
    calls: list[str] = []
    query = "经开区分公司注销登记（设区的市级权限）在哪里办理"
    service_name = "分公司注销登记（设区的市级权限）"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_metadata_service_hit("doc-vector", service_name="分公司设立登记（设区的市级权限）", score=0.68)]

    lexical_hit = _metadata_service_hit("doc-lexical-exact", service_name=service_name, score=0.92)
    db_hit_a = _metadata_service_hit("doc-db-exact-duplicate-a", service_name=service_name, score=1.0)
    db_hit_b = _metadata_service_hit("doc-db-exact-duplicate-b", service_name=service_name, score=0.98)

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(retriever, "_search_bm25", lambda **_kwargs: calls.append("bm25") or [], raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [lexical_hit],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_metadata_exact_anchor_db",
        lambda **_kwargs: calls.append("metadata_exact") or [db_hit_a, db_hit_b],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=5,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical", "metadata_exact"]
    assert {"doc-db-exact-duplicate-a", "doc-db-exact-duplicate-b"}.issubset(
        {item["document_id"] for item in results}
    )
    channels = retriever._last_channel_metrics
    assert channels["metadata_exact_db"]["enabled"] is True
    assert channels["metadata_exact_db"]["used"] is True
    assert channels["metadata_exact_db"]["candidates"] == 2
    assert channels["metadata_exact_db"]["run_reason"] == "hybrid_metadata_exact_fallback_enrich"
    assert channels["metadata_exact_db"]["protected_after_diversity_added"] == 1


def test_hybrid_mode_can_disable_cjk_metadata_exact_fallback_per_request(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(
        tenant_id=uuid4(),
        account_id="acct",
        lexical_db_hybrid_metadata_exact_fallback_enabled=False,
        metadata_exact_db_fallback_enabled=False,
    )
    calls: list[str] = []
    query = "企业在网上申报有何要求"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [
                _metadata_question_hit("doc-vector-1", question="企业在网上申报有何要求？"),
                _metadata_question_hit("doc-vector-2", question="从事贸易的企业如何申报？"),
            ]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25")
        or [
            _metadata_question_hit("doc-bm25-1", question="如何在网上申报"),
            _metadata_question_hit("doc-bm25-2", question="企业如何在线申请办理注册登记？"),
        ],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_metadata_question_hit("doc-lexical", question=query)],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_metadata_exact_anchor_db",
        lambda **_kwargs: calls.append("metadata_exact") or [_metadata_question_hit("doc-exact", question=query)],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25"]
    assert len(results) == 3
    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["used"] is False
    assert channels["lexical_db"]["run_reason"] == "skipped_primary_candidates_sufficient"
    assert channels["lexical_metadata_exact_fallback"] == {
        "enabled": False,
        "query_anchor_like": False,
        "primary_has_exact_anchor": False,
        "triggered": False,
    }
    assert channels["metadata_exact_db"] == {
        "enabled": False,
        "used": False,
        "candidates": 0,
        "run_reason": "disabled",
    }


def test_lexical_dataset_scope_extracts_dataset_id_in_filter() -> None:
    dataset_a = uuid4()
    dataset_b = uuid4()

    dataset_scope, dataset_label = HybridRetriever._lexical_dataset_scope(
        {"dataset_id": {"$in": [str(dataset_a), str(dataset_b), "not-a-uuid"]}}
    )

    assert dataset_scope == [dataset_a, dataset_b]
    assert dataset_label == str(dataset_a)
    assert all(isinstance(item, UUID) for item in dataset_scope)


def test_metadata_exact_db_result_uses_row_dataset_id_for_multi_dataset_filter() -> None:
    dataset_a = uuid4()
    dataset_b = uuid4()
    chunk_id = uuid4()
    tenant_id = uuid4()
    document_id = uuid4()
    query = "经开区分公司注销登记（设区的市级权限）在哪里办理"
    service_name = "分公司注销登记（设区的市级权限）"
    row = (
        chunk_id,
        f"事项名称：{service_name}",
        {
            "service_name": service_name,
            "retrieval_intents": [query],
            "gov_knowledge_type": "service_item",
        },
        tenant_id,
        document_id,
        0,
        None,
        dataset_b,
    )

    retriever = HybridRetriever(tenant_id=tenant_id, account_id="acct")
    parsed = retriever._metadata_exact_result_from_row(
        row,
        query=query,
        dataset_str=str(dataset_a),
        metadata_filter={"dataset_id": {"$in": [str(dataset_a), str(dataset_b)]}},
    )

    assert parsed is not None
    _cid, result = parsed
    assert result["metadata"]["dataset_id"] == str(dataset_b)


def test_metadata_exact_db_like_terms_include_cjk_parentheses_variant() -> None:
    query = "经开区分公司注销登记(设区的市级权限)在哪里办理"

    terms = HybridRetriever._metadata_exact_db_like_terms(query)

    assert query in terms
    assert "经开区分公司注销登记（设区的市级权限）在哪里办理" in terms


def test_hybrid_mode_uses_lexical_db_when_cjk_exact_metadata_anchor_is_missing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    retriever.enable_weight_rerank = False
    retriever.enable_reranker = False
    calls: list[str] = []
    query = "企业在网上申报有何要求"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [
                _metadata_question_hit("doc-vector-1", question="企业在网上申报有何要求？"),
                _metadata_question_hit("doc-vector-2", question="从事贸易的企业如何申报？"),
            ]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25")
        or [
            _metadata_question_hit("doc-bm25-1", question="如何在网上申报"),
            _metadata_question_hit("doc-bm25-2", question="企业如何在线申请办理注册登记？"),
        ],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_metadata_question_hit("doc-lexical", question=query)],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical"]
    assert results[0]["document_id"] == "doc-lexical"

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["used"] is True
    assert channels["lexical_db"]["run_reason"] == "hybrid_metadata_exact_fallback"
    assert channels["lexical_metadata_exact_fallback"] == {
        "enabled": True,
        "query_anchor_like": True,
        "primary_has_exact_anchor": False,
        "triggered": True,
    }


def test_hybrid_mode_still_uses_lexical_db_when_cjk_exact_metadata_anchor_is_present(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []
    query = "企业在网上申报有何要求"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_metadata_question_hit("doc-vector-1", question=query, score=10.0), _bm25_hit("doc-vector-2")]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25-1"), _bm25_hit("doc-bm25-2")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_metadata_question_hit("doc-lexical", question=query)],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical"]
    assert len(results) == 3

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["used"] is True
    assert channels["lexical_db"]["run_reason"] == "hybrid_metadata_exact_fallback"
    assert channels["lexical_metadata_exact_fallback"] == {
        "enabled": True,
        "query_anchor_like": True,
        "primary_has_exact_anchor": True,
        "triggered": True,
    }


def test_hybrid_metadata_exact_fallback_adds_metadata_anchor_candidates_when_lexical_misses(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []
    query = "不动产业务"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_bm25_hit("doc-regulation", score=0.95)]

    metadata_hit = _metadata_question_hit("doc-faq", question=query, score=1.0)
    metadata_hit["metadata"] = {
        **dict(metadata_hit["metadata"]),  # type: ignore[arg-type]
        "lexical_method": "metadata_exact",
        "gov_knowledge_type": "qa",
        "_evaluable_metadata": {"question": query, "gov_knowledge_type": "qa"},
    }

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-service", score=0.9)],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical-distractor", score=0.8)],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_metadata_exact_anchor_db",
        lambda **_kwargs: calls.append("metadata_exact") or [metadata_hit],
        raising=True,
    )

    results = retriever._hybrid_search(
        query=query,
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical", "metadata_exact"]
    assert results[0]["document_id"] == "doc-faq"
    assert results[0]["metadata_exact_match_field"] == "question"

    channels = retriever._last_channel_metrics
    assert channels["metadata_exact_db"] == {
        "enabled": True,
        "used": True,
        "candidates": 1,
        "run_reason": "hybrid_metadata_exact_fallback",
    }


def test_hybrid_reapplies_metadata_exact_ordering_after_weight_rerank(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    query = "不动产业务"

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            return [
                {
                    "document_id": "doc-regulation",
                    "chunk_id": "doc-regulation:0",
                    "content": "不动产登记暂行条例实施细则",
                    "score": 0.99,
                    "metadata": {"document_id": "doc-regulation", "chunk_id": "doc-regulation:0", "chunk_index": 0},
                    "vector_score": 0.99,
                }
            ]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: [_metadata_question_hit("doc-faq", question=query, score=0.2)],
        raising=True,
    )
    monkeypatch.setattr(retriever, "_search_metadata_exact_anchor_db", lambda **_kwargs: [], raising=True)

    results = retriever._hybrid_search(
        query=query,
        top_k=2,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
        enable_weight_rerank=True,
    )

    assert results[0]["document_id"] == "doc-faq"
    assert results[0]["metadata_exact_match_field"] == "question"
    channels = retriever._last_channel_metrics
    assert channels["metadata_exact_pre_dedup_ordering"]["applied"] is True
    assert channels["metadata_exact_final_ordering"]["applied"] is True
    assert channels["metadata_exact_final_ordering"]["annotated"] == 1


def test_hybrid_mode_uses_lexical_db_when_primary_channels_are_insufficient(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return []

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical"]
    assert len(results) == 1

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["used"] is True
    assert channels["lexical_db"]["run_reason"] == "hybrid_fallback"
    assert channels["counts"]["lexical_candidates"] == 1
