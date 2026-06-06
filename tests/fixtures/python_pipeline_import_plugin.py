from __future__ import annotations

from langchain_core.documents import Document


def govern_documents(documents, params=None, context=None):  # noqa: ANN001
    if documents:
        return documents
    return [
        Document(
            page_content="legacy import governance fixture",
            metadata={"legacy_import_plugin": "fixture"},
        )
    ]


def chunk_documents(documents, params=None, context=None):  # noqa: ANN001
    return list(documents or [])


def build_kg_events(documents, params=None, context=None):  # noqa: ANN001
    return []
