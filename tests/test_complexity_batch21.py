
import datetime as dt

import starlette.status as starlette_status
from langchain_core.documents import Document


def test_build_context_applies_denoise_compress_and_reorder_in_sequence(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(dt, "UTC", dt.timezone.utc, raising=False)
    monkeypatch.setattr(
        starlette_status,
        "HTTP_413_CONTENT_TOO_LARGE",
        getattr(starlette_status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413),
        raising=False,
    )
    monkeypatch.setattr(
        starlette_status,
        "HTTP_422_UNPROCESSABLE_CONTENT",
        getattr(starlette_status, "HTTP_422_UNPROCESSABLE_ENTITY", 422),
        raising=False,
    )
    import app.rag.pipelines.langgraph as graph

    order: list[str] = []
    base_doc = Document(page_content="alpha", metadata={"source": "doc.txt"})

    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_LLM_COMPRESSION_ENABLED", False, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_COMPRESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_REORDER_ENABLED", True, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_EVIDENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_MAX_CHARS_PER_CHUNK", 0, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_MAX_TOTAL_CHARS", 0, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0, raising=False)
    monkeypatch.setattr(graph.settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0, raising=False)

    monkeypatch.setattr(
        graph,
        "_denoise_context_docs",
        lambda docs: order.append("denoise") or [Document(page_content="denoised", metadata=docs[0].metadata)],
        raising=True,
    )
    monkeypatch.setattr(
        graph,
        "_compress_context_docs",
        lambda docs, query=None: (
            order.append(f"compress:{query}") or [Document(page_content="compressed", metadata=docs[0].metadata)]
        ),  # noqa: ARG005,E501
        raising=True,
    )
    monkeypatch.setattr(
        graph,
        "_reorder_context_docs",
        lambda docs: order.append("reorder") or list(reversed(docs)),
        raising=True,
    )

    rendered = graph._build_context([base_doc], query="what")

    assert order == ["denoise", "compress:what", "reorder"]
    assert "compressed" in rendered


def test_safe_kg_path_provenance_drops_empty_and_bounds_fields() -> None:
    from app.rag.retrieval.orchestrator import _safe_kg_path_provenance

    cleaned = _safe_kg_path_provenance(
        {
            "schema": "mimirq.kg.v1",
            "kind": "shortest_path",
            "hops": "3",
            "nodes": [
                {"kind": "entity", "entity_id": "e1", "chunk_id": "c1", "ignored": "x"},
                {"kind": "", "entity_id": ""},
            ],
            "edges": [
                {"kind": "relation", "predicate": "uses", "relation_id": "r1", "evidence_source": "kg"},
                {"kind": "", "predicate": ""},
            ],
        }
    )

    assert cleaned == {
        "schema": "mimirq.kg.v1",
        "kind": "shortest_path",
        "hops": 3,
        "nodes": [{"kind": "entity", "entity_id": "e1", "chunk_id": "c1"}],
        "edges": [{"kind": "relation", "predicate": "uses", "relation_id": "r1", "evidence_source": "kg"}],
    }


def test_calibrate_post_rerank_prefix_docs_reorders_when_rerank_scores_available() -> None:
    from app.rag.retrieval.orchestrator import _calibrate_post_rerank_prefix_docs

    docs = [
        Document(page_content="a", metadata={"score": 0.9, "retrieval_score": 0.9, "rerank_score": 0.1}, id="a"),
        Document(page_content="b", metadata={"score": 0.2, "retrieval_score": 0.2, "rerank_score": 0.9}, id="b"),
    ]
    stats = {"enabled": True, "alpha": 0.7, "used": False}

    calibrated, used = _calibrate_post_rerank_prefix_docs(docs, enabled=True, alpha=0.7, stats=stats)

    assert used is True
    assert [doc.id for doc in calibrated] == ["b", "a"]
    assert stats["used"] is True
    assert stats["eligible_docs"] == 2
