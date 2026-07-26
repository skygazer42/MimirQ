"""Mixins and shared helpers for the HybridRetriever.

This package exists to keep ``app/rag/retriever.py`` at a maintainable size:
each mixin owns one retrieval concern (BM25 index, sparse index, ColBERT index,
lexical DB search, fusion, dedup/diversity, post-processing) while the pydantic
model definition, orchestration, and public surface stay in ``app.rag.retriever``.

Import direction: mixins may import from ``app.rag.retrieval.hybrid.common`` and
leaf modules only — never from ``app.rag.retriever`` (circular). Anything the
mixins need from the retriever module at call time must go through a hook method
defined on the core class (e.g. ``_open_session``) so tests that monkeypatch
``app.rag.retriever`` module attributes keep working.
"""
