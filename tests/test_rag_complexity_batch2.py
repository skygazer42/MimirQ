import threading
from collections import OrderedDict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document as LangChainDocument

from app.models.chunk import Document as ChunkDocument
from app.rag.chunking.strategies.parent_child import ParentChildChunker
from app.rag.preprocessing.cleaning import RegexRule
from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES, build_governance_rules
from app.rag.reranker.hybrid import KeywordSetting, VectorSetting, WeightedReranker, Weights
from app.rag.retrieval.document_structure import build_document_structure_from_chunks
from app.rag.retrieval.hybrid.bm25_index import Bm25IndexMixin
from app.rag.retrieval.orchestration.kg_merge_boost import _merge_kg_metadata_into_main
from app.rag.workflows.evaluator_optimizer import EvaluatorOptimizerWorkflow


def test_parent_child_chunker_reuses_cached_splits_without_sharing_mutations() -> None:
    chunker = ParentChildChunker(
        chunk_size=80,
        chunk_overlap=10,
        child_ratio=0.5,
        min_child_size=20,
    )
    doc = LangChainDocument(
        page_content="Alpha beta gamma delta. " * 12,
        metadata={"source": "characterization"},
    )

    first = chunker.split_documents([doc])
    second = chunker.split_documents([doc])

    assert first
    assert second
    assert all(left is not right for left, right in zip(first, second, strict=False))
    assert {item.metadata["chunk_role"] for item in first} == {"parent", "child"}

    parent = next(item for item in first if item.metadata["chunk_role"] == "parent")
    child = next(item for item in first if item.metadata["chunk_role"] == "child")
    assert child.metadata["parent_id"] == parent.metadata["parent_id"]

    second[0].metadata["mutated"] = True
    third = chunker.split_documents([doc])

    assert "mutated" not in third[0].metadata


def test_build_governance_rules_expands_unique_packs_and_sanitizes_extra_rules() -> None:
    rules = build_governance_rules(
        extra_rules=[
            {"pattern": "alpha", "repl": None, "flags": "2"},
            {"pattern": "beta", "repl": 123, "flags": "invalid"},
            {"pattern": "   "},
            "skip",
        ],
        rule_packs=["WEB_COOKIE_BANNERS", " web_cookie_banners ", "unknown", 3],
    )

    assert rules[: len(DEFAULT_MARKDOWN_RULES)] == DEFAULT_MARKDOWN_RULES
    assert (
        rules[
            len(DEFAULT_MARKDOWN_RULES) : len(DEFAULT_MARKDOWN_RULES) + len(GOVERNANCE_RULE_PACKS["web_cookie_banners"])
        ]
        == (GOVERNANCE_RULE_PACKS["web_cookie_banners"])
    )
    assert rules[-2:] == [
        RegexRule(pattern="alpha", repl="", flags=2),
        RegexRule(pattern="beta", repl="123", flags=0),
    ]


def test_weighted_reranker_keyword_scores_use_current_keyword_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeKeywordHandler:
        def extract_keywords(self, text: str, _max_keywords_per_chunk: object) -> list[str]:
            mapping = {
                "query": ["alpha", "alpha", "beta"],
                "doc-a": ["alpha", "beta"],
                "doc-b": ["gamma"],
            }
            return list(mapping[text])

    monkeypatch.setattr("app.rag.preprocessing.keyword.JiebaKeywordTableHandler", _FakeKeywordHandler)

    reranker = WeightedReranker(
        tenant_id="tenant",
        weights=Weights(
            vector_setting=VectorSetting(
                vector_weight=0.5,
                embedding_provider_name="provider",
                embedding_model_name="model",
            ),
            keyword_setting=KeywordSetting(keyword_weight=0.5),
        ),
    )
    documents = [
        ChunkDocument(page_content="doc-a", metadata={}),
        ChunkDocument(page_content="doc-b", metadata={}),
    ]

    scores = reranker._calculate_keyword_score("query", documents)

    assert documents[0].metadata["keywords"] == ["alpha", "beta"]
    assert documents[1].metadata["keywords"] == ["gamma"]
    assert scores[0] > 0.0
    assert scores[1] == 0.0


def test_build_document_structure_aggregates_nested_paths_and_metadata() -> None:
    document = SimpleNamespace(
        id="doc-1",
        filename="guide.pdf",
        file_type="pdf",
        doc_metadata={"page_count": 8, "description": "Guide"},
    )
    chunks = [
        SimpleNamespace(
            id="chunk-1",
            chunk_index=0,
            page_number=3,
            doc_metadata={
                "header_path": ["Intro", "Overview"],
                "hierarchy_node_key": "node-a",
                "hierarchy_family_key": "family-a",
            },
        ),
        SimpleNamespace(
            id="chunk-2",
            chunk_index=1,
            page_number=5,
            doc_metadata={"header_path": ["Intro", "Overview"]},
        ),
    ]

    structure = build_document_structure_from_chunks(document=document, chunks=chunks, max_nodes=10)

    assert structure["document"]["document_id"] == "doc-1"
    assert structure["node_count"] == 2
    assert structure["source_chunk_count"] == 2
    root = structure["nodes"][0]
    child = root["children"][0]
    assert root["title"] == "Intro"
    assert child["title"] == "Overview"
    assert child["chunk_ids"] == ["chunk-1", "chunk-2"]
    assert child["chunk_indexes"] == [0, 1]
    assert child["page_start"] == 3
    assert child["page_end"] == 5
    assert child["node_key"] == "node-a"
    assert child["family_key"] == "family-a"


def test_build_document_structure_marks_truncation_after_max_nodes() -> None:
    document = SimpleNamespace(id="doc-2", filename="outline.pdf", file_type="pdf", doc_metadata={})
    chunks = [
        SimpleNamespace(
            id="chunk-1",
            chunk_index=0,
            page_number=2,
            doc_metadata={"header_path": ["Root", "Child"], "hierarchy_node_key": "fallback-node"},
        ),
    ]

    structure = build_document_structure_from_chunks(document=document, chunks=chunks, max_nodes=1)

    assert structure["truncated"] is True
    assert structure["node_count"] == 1
    assert structure["nodes"][0]["chunk_ids"] == []
    assert structure["nodes"][0]["node_key"] is None


class _FakeBm25Retriever(Bm25IndexMixin):
    def __init__(self, dataset_id):
        self.dataset_id = dataset_id
        self.dataset_ids = None
        self.sparse_enabled = False
        self._bm25_cache_lock = threading.Lock()
        self._bm25_docs = {}
        self._bm25_retrievers = {}
        self._bm25_doc_ids = {}
        self._chunk_id_lookup = {}
        self._bm25_deferred_scopes = set()
        self._bm25_cache_versions = {}
        self._sparse_doc_vectors = {}
        self._colbert_index_cache = {}
        self._bm25_cache_order = OrderedDict()
        self._bm25_build_locks = {}
        self._sparse_build_locks = {}
        self._colbert_build_locks = {}
        self.replace_calls = []
        self.sparse_sync_calls = []
        self.colbert_sync_calls = []
        self.cleared_tenant_ids = []

    def _tenant_key(self, tenant_id):
        return str(tenant_id)

    @staticmethod
    def _resolve_tenant_uuid(tenant_id):
        return tenant_id

    @classmethod
    def _normalize_dataset_scope_ids(cls, dataset_scope_ids):
        return tuple(sorted({item for item in dataset_scope_ids or [] if item is not None}, key=str))

    def _explicit_dataset_scope_ids(self):
        return (self.dataset_id,) if self.dataset_id is not None else ()

    def _clear_candidate_corpus_token_cache(self, tenant_id):
        self.cleared_tenant_ids.append(tenant_id)

    def _effective_sparse_enabled(self):
        return False

    def _prepare_retrieval_document(self, doc):
        return doc

    def _replace_bm25_scope_index(self, *, cache_key: str, merged_docs):
        self.replace_calls.append((cache_key, [doc.id for doc in merged_docs]))

    def _sync_sparse_index_after_bm25_upsert(self, **kwargs):
        self.sparse_sync_calls.append(kwargs)

    def _sync_colbert_index_after_bm25_upsert(self, **kwargs):
        self.colbert_sync_calls.append(kwargs)


def test_upsert_bm25_documents_clears_document_scopes_and_eagerly_rebuilds_dataset_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    tenant_id = uuid4()
    dataset_id = uuid4()
    doc_id = uuid4()
    retriever = _FakeBm25Retriever(dataset_id=dataset_id)
    document_scope_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        dataset_ids=(),
        document_ids=[doc_id],
    )
    dataset_scope_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        dataset_ids=(dataset_id,),
        document_ids=None,
    )
    existing_doc = LangChainDocument(
        page_content="existing",
        id="existing-chunk",
        metadata={"document_id": str(uuid4()), "dataset_id": str(dataset_id), "chunk_index": 0},
    )
    upsert_doc = LangChainDocument(
        page_content="upsert",
        id="upsert-chunk",
        metadata={"document_id": str(uuid4()), "dataset_id": str(dataset_id), "chunk_index": 1},
    )
    retriever._bm25_docs[document_scope_key] = [existing_doc]
    retriever._bm25_retrievers[document_scope_key] = object()
    retriever._bm25_deferred_scopes.add(document_scope_key)
    retriever._bm25_docs[dataset_scope_key] = [existing_doc]
    retriever._bm25_retrievers[dataset_scope_key] = object()

    monkeypatch.setattr(settings, "BM25_EAGER_UPSERT_MAX_CHUNKS", 50, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False, raising=False)

    retriever.upsert_bm25_documents([upsert_doc], tenant_id=tenant_id)

    assert retriever.cleared_tenant_ids == [tenant_id]
    assert document_scope_key not in retriever._bm25_docs
    assert document_scope_key not in retriever._bm25_retrievers
    assert document_scope_key not in retriever._bm25_deferred_scopes
    assert retriever.replace_calls == [
        (
            dataset_scope_key,
            ["existing-chunk", "upsert-chunk"],
        )
    ]
    assert [doc.id for doc in retriever.sparse_sync_calls[0]["merged_docs"]] == ["existing-chunk", "upsert-chunk"]
    assert [doc.id for doc in retriever.colbert_sync_calls[0]["merged_docs"]] == ["existing-chunk", "upsert-chunk"]


def test_merge_kg_metadata_into_main_preserves_main_content_and_combines_fields() -> None:
    main_doc = LangChainDocument(
        page_content="main",
        id="main-id",
        metadata={
            "kg_pagerank": 0.2,
            "kg_path_length": 5,
            "kg_shared_events": 1,
            "kg_evidence_anchored": False,
        },
    )
    kg_doc = LangChainDocument(
        page_content="kg",
        id="kg-id",
        metadata={
            "kg_pagerank": 0.8,
            "kg_path": ["a", "b"],
            "kg_path_provenance": "graph",
            "kg_path_length": 3,
            "kg_shared_events": 4,
            "kg_evidence_anchored": True,
            "chunk_id": "kg-chunk",
        },
    )

    merged = _merge_kg_metadata_into_main(main_doc, kg_doc)

    assert merged.page_content == "main"
    assert merged.id == "main-id"
    assert merged.metadata["kg_pagerank"] == 0.8
    assert merged.metadata["kg_path"] == ["a", "b"]
    assert merged.metadata["kg_path_provenance"] == "graph"
    assert merged.metadata["kg_path_length"] == 3
    assert merged.metadata["kg_shared_events"] == 4
    assert merged.metadata["kg_evidence_anchored"] is True
    assert merged.metadata["kg_duplicate_candidate"] is True


@pytest.mark.asyncio
async def test_default_evaluate_without_llm_uses_heuristic_pass_signal() -> None:
    workflow = EvaluatorOptimizerWorkflow(llm=None)
    contexts = [{"content": "Shared evidence sentence."}, {"content": "Other context"}]
    answer = (
        "Shared evidence sentence. "
        "This answer is intentionally long enough to cross the first heuristic threshold. "
        "It also stays under two hundred characters."
    )

    result = await workflow._default_evaluate("question", answer, contexts)

    assert result.score == pytest.approx(0.9)
    assert result.feedback == "Heuristic evaluation"
    assert result.criteria_scores == {}


@pytest.mark.asyncio
async def test_default_evaluate_parses_scores_and_ignores_invalid_lines() -> None:
    class _FakeResponse:
        content = "\n".join(
            [
                "Relevance: 0.8",
                "Accuracy: invalid",
                "Completeness: 0.6",
                "Overall: 0.7",
                "Feedback: tighten the claim",
            ]
        )

    class _FakeLlm:
        async def ainvoke(self, _prompt: str) -> _FakeResponse:
            return _FakeResponse()

    workflow = EvaluatorOptimizerWorkflow(llm=_FakeLlm())

    result = await workflow._default_evaluate(
        "question",
        "answer",
        [{"content": "context one"}, {"content": "context two"}],
    )

    assert result.score == 0.7
    assert result.feedback == "tighten the claim"
    assert result.criteria_scores == {
        "relevance": 0.8,
        "completeness": 0.6,
    }
