"""Mixins and shared helpers for the RAGEngine.

This package exists to keep ``app/rag/engine.py`` at a maintainable size:
each module owns one engine concern (stream_chat input plumbing and shared
constants, LLM build/routing, pure document utilities) while ``__init__``,
``stream_chat``, and the singleton factory stay in ``app.rag.engine``.

Stream phases import their dependencies from the actual function owners.
Request state carries the engine and request-local values; it does not carry
the engine module as a dependency container. Type-only engine references and
lazy agent imports preserve the initialization order.

This package intentionally does not re-export anything.
"""
