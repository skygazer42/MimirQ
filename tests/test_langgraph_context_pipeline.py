from langchain_core.documents import Document


def test_langgraph_build_context_applies_denoise_before_formatting(monkeypatch):
    import app.rag.pipelines.langgraph as lg_mod

    docs = [
        Document(page_content="keep", metadata={"source": "a"}),
        Document(page_content="drop", metadata={"source": "b"}),
    ]

    monkeypatch.setattr(
        "app.rag.core.context_denoise.denoise_context_docs",
        lambda incoming: [incoming[0]],
    )

    out = lg_mod._build_context(docs, query="why")
    assert "keep" in out
    assert "drop" not in out


def test_reorder_docs_for_generation_interleaves_high_and_low_ranked_docs():
    from app.rag.core.doc_ordering import reorder_docs_for_generation

    docs = ["d1", "d2", "d3", "d4", "d5"]
    assert reorder_docs_for_generation(docs) == ["d1", "d3", "d5", "d4", "d2"]


def test_langgraph_build_context_applies_optional_reorder(monkeypatch) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    docs = [
        Document(page_content='alpha', metadata={'source': 'a'}),
        Document(page_content='beta', metadata={'source': 'b'}),
        Document(page_content='gamma', metadata={'source': 'c'}),
    ]

    monkeypatch.setattr(settings, 'RAG_CONTEXT_REORDER_ENABLED', True, raising=False)
    monkeypatch.setattr('app.rag.core.context_denoise.denoise_context_docs', lambda incoming: list(incoming))
    monkeypatch.setattr('app.rag.core.doc_ordering.reorder_docs_for_generation', lambda incoming: list(reversed(incoming)))

    out = lg_mod._build_context(docs, query='why')

    assert out.startswith('[Source 1: c]')
    assert out.index('[Source 2: b]') > out.index('[Source 1: c]')
    assert out.index('[Source 3: a]') > out.index('[Source 2: b]')
