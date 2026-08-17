from langchain_core.documents import Document

from app.rag.retrieval.context_expansion import expand_ranked_chunk_results
from app.rag.retrieval.contextual_followup import build_contextual_followup_query
from app.rag.retrieval.hierarchy_expand import expand_hierarchy_context
from app.rag.retriever import HybridRetriever


class _Chunk:
    def __init__(
        self,
        *,
        chunk_id: str,
        document_id: str,
        chunk_index: int,
        content: str,
        header_path: str = "Section A",
        source: str = "fixture",
    ) -> None:
        self.id = chunk_id
        self.tenant_id = "tenant-1"
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = None
        self.doc_metadata = {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "header_path": header_path,
            "source": source,
        }


def _result(*, doc_id: str, chunk_index: int, score: float, content: str = "") -> dict[str, object]:
    chunk_id = f"{doc_id}:{chunk_index}"
    return {
        "chunk_id": chunk_id,
        "content": content or f"chunk {chunk_id}",
        "metadata": {
            "document_id": doc_id,
            "chunk_index": chunk_index,
            "chunk_id": chunk_id,
        },
        "score": float(score),
    }


def test_expand_ranked_chunk_results_preserves_order_dedup_scores_and_provenance() -> None:
    neighbors = {
        ("doc-1", 0): _Chunk(chunk_id="doc-1:0", document_id="doc-1", chunk_index=0, content="left"),
        ("doc-1", 2): _Chunk(chunk_id="doc-1:2", document_id="doc-1", chunk_index=2, content="shared"),
        ("doc-1", 4): _Chunk(chunk_id="doc-1:4", document_id="doc-1", chunk_index=4, content="right"),
    }

    out, meta = expand_ranked_chunk_results(
        results=[
            {
                "chunk_id": "doc-1:1",
                "content": "anchor-1",
                "metadata": {
                    "document_id": "doc-1",
                    "chunk_index": 1,
                    "chunk_id": "doc-1:1",
                    "header_path": "Section A",
                },
                "score": 1.0,
            },
            {
                "chunk_id": "doc-1:3",
                "content": "anchor-2",
                "metadata": {
                    "document_id": "doc-1",
                    "chunk_index": 3,
                    "chunk_id": "doc-1:3",
                    "header_path": "Section A",
                },
                "score": 0.6,
            },
        ],
        window=1,
        max_added=10,
        sibling_max_added=0,
        neighbors_by_pair=neighbors,
    )

    assert [item["content"] for item in out] == ["left", "anchor-1", "shared", "anchor-2", "right"]
    assert [item["chunk_id"] for item in out].count("doc-1:2") == 1
    assert out[0]["metadata"]["retrieval_role"] == "neighbor"
    assert out[0]["metadata"]["neighbor_of"] == "doc-1:1"
    assert out[0]["score"] == 0.85
    assert out[-1]["metadata"]["neighbor_of"] == "doc-1:3"
    assert out[-1]["score"] == 0.51
    assert meta["neighbor_added"] == 3
    assert meta["strategy"] == "neighbor"


def test_expand_ranked_chunk_results_respects_window_and_global_max_added() -> None:
    out, meta = expand_ranked_chunk_results(
        results=[
            {
                "chunk_id": "doc-2:5",
                "content": "anchor",
                "metadata": {
                    "document_id": "doc-2",
                    "chunk_index": 5,
                    "chunk_id": "doc-2:5",
                    "header_path": "Section B",
                },
                "score": 0.5,
            }
        ],
        window=2,
        max_added=2,
        sibling_max_added=0,
        neighbors_by_pair={
            (
                "doc-2",
                3,
            ): _Chunk(
                chunk_id="doc-2:3",
                document_id="doc-2",
                chunk_index=3,
                content="far-left",
                header_path="Section B",
            ),
            (
                "doc-2",
                4,
            ): _Chunk(
                chunk_id="doc-2:4",
                document_id="doc-2",
                chunk_index=4,
                content="left",
                header_path="Section B",
            ),
            (
                "doc-2",
                6,
            ): _Chunk(
                chunk_id="doc-2:6",
                document_id="doc-2",
                chunk_index=6,
                content="right",
                header_path="Section B",
            ),
            (
                "doc-2",
                7,
            ): _Chunk(
                chunk_id="doc-2:7",
                document_id="doc-2",
                chunk_index=7,
                content="far-right",
                header_path="Section B",
            ),
        },
    )

    assert [item["content"] for item in out] == ["far-left", "left", "anchor"]
    assert meta["neighbor_added"] == 2
    assert meta["added_docs"] == 2


def test_build_contextual_followup_query_normalizes_clauses_and_gap_terms() -> None:
    docs = [
        Document(
            page_content="OAuth2 token revocation and session reset details.",
            metadata={
                "keywords": ["OAuth2", "reset"],
                "tags": ["Auth", "oauth2"],
                "title": "Reset Playbook",
                "source": "auth-runbook",
            },
        )
    ]

    result = build_contextual_followup_query(
        query="  How   to reset login error  ",
        docs=docs,
        evidence_gap={"missing_source_keys": ["Inventory Table"], "anchor_missing_any": 1},
        max_docs=1,
        max_terms=4,
    )

    assert result["query"] == "How to reset login error Inventory Table OAuth2 Auth"
    assert result["used"] is True
    assert result["selected_terms"] == ["Inventory", "Table", "OAuth2", "Auth"]
    assert result["reason_codes"] == [
        "gap_missing_source_keys",
        "gap_missing_anchor_fields",
        "selected_terms",
    ]
    assert result["docs_considered"] == 1
    assert result["terms_considered"] >= 4


def test_build_contextual_followup_query_respects_doc_and_query_length_limits() -> None:
    docs = [
        Document(page_content="Alpha keyword expansion", metadata={"keywords": ["Alpha"]}),
        Document(page_content="Beta keyword expansion", metadata={"keywords": ["Beta"]}),
    ]

    result = build_contextual_followup_query(
        query="base",
        docs=docs,
        max_docs=1,
        max_terms=1,
        max_query_chars=10,
    )

    assert result["docs_considered"] == 1
    assert result["selected_terms"] == ["Alpha"]
    assert result["query"] == "base Alpha"


def test_expand_hierarchy_context_traverses_parents_uses_fallback_keys_and_scopes_siblings() -> None:
    requested: list[set[tuple[str, str]]] = []
    anchor = Document(
        page_content="anchor",
        metadata={
            "document_id": "doc-3",
            "chunk_index": 1,
            "chunk_id": "doc-3:1",
            "chunk_key": "node-1",
            "parent_id": "parent-1",
            "prev_chunk_key": "sib-0",
            "next_chunk_key": "sib-2",
            "_record_identity": {"key": "record-a"},
            "score": 1.0,
        },
        id="doc-3:1",
    )
    trailing = Document(
        page_content="trailing",
        metadata={"document_id": "plain-doc", "chunk_index": 0, "chunk_id": "plain-doc:0"},
        id="plain-doc:0",
    )
    parent = Document(
        page_content="parent",
        metadata={
            "document_id": "doc-3",
            "chunk_index": 10,
            "chunk_id": "doc-3:10",
            "chunk_key": "parent-1",
            "parent_node_id": "root-1",
        },
        id="doc-3:10",
    )
    root = Document(
        page_content="root",
        metadata={
            "document_id": "doc-3",
            "chunk_index": 11,
            "chunk_id": "doc-3:11",
            "chunk_key": "root-1",
            "hierarchy_parent_key": None,
        },
        id="doc-3:11",
    )
    left_sibling = Document(
        page_content="left-sibling",
        metadata={
            "document_id": "doc-3",
            "chunk_index": 0,
            "chunk_id": "doc-3:0",
            "chunk_key": "sib-0",
            "_record_identity": {"key": "record-a"},
        },
        id="doc-3:0",
    )
    right_sibling = Document(
        page_content="right-sibling",
        metadata={
            "document_id": "doc-3",
            "chunk_index": 2,
            "chunk_id": "doc-3:2",
            "chunk_key": "sib-2",
            "_record_identity": {"key": "record-b"},
        },
        id="doc-3:2",
    )
    by_pair = {
        ("doc-3", "parent-1"): parent,
        ("doc-3", "root-1"): root,
        ("doc-3", "sib-0"): left_sibling,
        ("doc-3", "sib-2"): right_sibling,
    }

    def fetch_by_key(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], Document]:
        requested.append(set(pairs))
        return {pair: by_pair[pair] for pair in pairs if pair in by_pair}

    out, meta = expand_hierarchy_context(
        [anchor, trailing],
        parent_depth=2,
        sibling_window=1,
        fetch_by_key=fetch_by_key,
        max_added_docs=5,
    )

    assert [doc.page_content for doc in out] == ["root", "parent", "left-sibling", "anchor", "trailing"]
    assert set().union(*requested) == {
        ("doc-3", "parent-1"),
        ("doc-3", "root-1"),
        ("doc-3", "sib-0"),
        ("doc-3", "sib-2"),
    }
    assert out[0].metadata["retrieval_role"] == "hierarchy_parent"
    assert out[1].metadata["neighbor_of"] == "doc-3:1"
    assert out[2].metadata["retrieval_role"] == "hierarchy_sibling"
    assert meta["added_docs"] == 3
    assert meta["added_parents"] == 2
    assert meta["added_siblings"] == 1
    assert meta["skipped_cross_record_siblings"] == 1


def test_weighted_fusion_respects_channel_weights_ties_and_metadata_fill() -> None:
    retriever = HybridRetriever().model_copy(update={"fusion_weights": {"vector": 2, "bm25": 2}})

    vector = [
        _result(doc_id="d1", chunk_index=0, score=10.0, content="vector winner"),
        _result(doc_id="d3", chunk_index=0, score=1.0, content="shared"),
    ]
    vector[1]["metadata"]["source"] = ""

    bm25 = [
        _result(doc_id="d2", chunk_index=0, score=10.0, content="bm25 winner"),
        _result(doc_id="d3", chunk_index=0, score=1.0, content="shared"),
    ]
    bm25[1]["metadata"]["source"] = "bm25-source"
    bm25[1]["metadata"]["table_id"] = "table-9"

    out = retriever._merge_results(vector, bm25, fusion_strategy="weighted")

    assert [retriever._result_key(item) for item in out[:3]] == ["d1:0", "d2:0", "d3:0"]
    assert out[2]["metadata"]["source"] == "bm25-source"
    assert out[2]["metadata"]["table_id"] == "table-9"
    assert retriever._last_channel_metrics["fusion_weighted"]["weights"] == {"bm25": 0.5, "vector": 0.5}


def test_budgeted_rrf_prefix_limits_visible_selection_and_marks_prefix_rank() -> None:
    retriever = HybridRetriever()

    out = retriever._merge_results(
        [_result(doc_id="d1", chunk_index=0, score=9.0)],
        [_result(doc_id="d2", chunk_index=0, score=8.0)],
        [_result(doc_id="d3", chunk_index=0, score=7.0)],
        [],
        fusion_strategy="budgeted_rrf",
        top_k=2,
        rrf_k=60,
    )

    prefix_ranks = [item.get("fusion_budgeted_prefix_rank") for item in out]
    assert prefix_ranks[:2] == [1, 2]
    assert prefix_ranks[2:] == [None]
    assert retriever._last_channel_metrics["fusion_budgeted_rrf"]["selected_prefix"] == 2
    assert retriever._last_channel_metrics["fusion_budgeted_rrf"]["budgets"] == {
        "bm25": 1,
        "lexical": 0,
        "sparse": 0,
        "vector": 1,
    }
