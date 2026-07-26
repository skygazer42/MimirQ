"""Mixins and shared helpers for the RAGEngine.

This package exists to keep ``app/rag/engine.py`` at a maintainable size:
each module owns one engine concern (stream_chat input plumbing and shared
constants, LLM build/routing, pure document utilities) while ``__init__``,
``stream_chat``, and the singleton factory stay in ``app.rag.engine``.

Import direction: submodules may import leaf modules only — never
``app.rag.engine`` and never ``app.rag.retrieval.orchestrator`` (circular).
Anything the mixins need from the engine module at call time must go through
attributes/methods defined on the core class so tests that monkeypatch
``app.rag.engine`` module attributes keep working.

This package intentionally does not re-export anything.
"""
