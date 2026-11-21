"""Compress retrieved context with the configured language model and existing failure policy."""

import logging
from collections.abc import Iterable

from langchain_core.documents import Document

from app.infrastructure.config import settings

logger = logging.getLogger(__name__)


def _compress_text_with_llm(*, text: str, query: str) -> str:
    if not text or not query:
        return text

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from app.rag.runtime.engine import get_rag_engine

    engine = get_rag_engine()
    llm = engine.models.get("fast")
    if llm is None:
        llm = engine.models["default"]

    prompt = ChatPromptTemplate.from_template(
        """Extract only the information relevant to the query from the following text.
Keep key facts, numbers, and relationships. Remove filler and irrelevant details.

Query: {query}
Text:
{text}

Relevant information:"""
    )
    chain = prompt | llm.bind(temperature=0.0) | StrOutputParser()
    try:
        out = chain.invoke({"query": query, "text": text})
    except Exception as exc:
        logger.debug("Context compression failed (%s)", type(exc).__name__)
        return text
    compressed = out.strip()
    if not compressed:
        return text
    return compressed


def compress_context_docs_with_llm(
    docs: Iterable[Document] | None,
    *,
    query: str | None = None,
) -> list[Document]:
    if not docs:
        return []
    if not settings.RAG_CONTEXT_LLM_COMPRESSION_ENABLED:
        return list(docs)

    query_text = str(query or "").strip()
    if not query_text:
        return list(docs)

    out: list[Document] = []
    for doc in docs:
        text = doc.page_content.strip()
        if not text:
            continue
        compressed = _compress_text_with_llm(text=text, query=query_text)
        out.append(Document(page_content=compressed, metadata=dict(doc.metadata), id=doc.id))
    return out


__all__ = ["compress_context_docs_with_llm"]
