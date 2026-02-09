from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun


def test_normalize_query_noop_when_already_canonical() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("hello world")
    assert out.normalized_text == "hello world"
    assert out.applied_rules == []


def test_normalize_query_whitespace_canonicalization() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("  hello   world \n")
    assert out.normalized_text == "hello world"
    assert out.applied_rules == ["whitespace"]


def test_normalize_query_fullwidth_nfkc() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("ＡＢＣ１２３")
    assert out.normalized_text == "ABC123"
    assert out.applied_rules == ["nfkc"]


def test_normalize_query_numeric_commas() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("1,000")
    assert out.normalized_text == "1000"
    assert out.applied_rules == ["numeric_commas"]


def test_normalize_query_version_prefix_v() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("v1.2.3")
    assert out.normalized_text == "1.2.3"
    assert out.applied_rules == ["version_prefix_v"]


def test_normalize_query_path_separators() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query(r"C:\\Users\\me")
    assert out.normalized_text == "C:/Users/me"
    assert out.applied_rules == ["path_separators"]


def test_normalize_query_unit_case() -> None:
    from app.query.normalize import normalize_query

    out = normalize_query("10mb")
    assert out.normalized_text == "10MB"
    assert out.applied_rules == ["unit_case"]


def test_hybrid_retriever_normalizes_query_before_search(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    captured: dict[str, str] = {}

    retriever = HybridRetriever(k=5)

    def _hybrid_search_stub(*, query: str, **_kwargs):  # noqa: ANN001
        captured["query"] = query
        return []

    # Avoid DB / neighbor side effects; we're only asserting the query passed into the search.
    monkeypatch.setattr(retriever, "_hybrid_search", _hybrid_search_stub, raising=True)
    monkeypatch.setattr(retriever, "_enrich_results_with_db_metadata", lambda results, stats=None: results, raising=True)  # noqa: E501
    monkeypatch.setattr(retriever, "_expand_results_with_neighbors", lambda results: results, raising=True)
    monkeypatch.setattr(retriever, "_auto_merge_parent_child", lambda results: results, raising=True)

    retriever._get_relevant_documents("1,000", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert captured.get("query") == "1000"
