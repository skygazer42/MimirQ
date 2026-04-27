from __future__ import annotations

import inspect
from typing import Any

from app.rag.tools.mcp_tools import get_document_content, search_documents


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def keyword_search(query: str, *, dataset_id: str, top_k: int = 5) -> dict[str, Any]:
    return await _maybe_await(search_documents(query=query, top_k=top_k, dataset_id=dataset_id))


async def semantic_search(query: str, *, dataset_id: str, top_k: int = 5) -> dict[str, Any]:
    return await _maybe_await(search_documents(query=query, top_k=top_k, dataset_id=dataset_id))


async def chunk_read(
    *,
    document_id: str,
    dataset_id: str,
    page: int | None = None,
    account_id: str | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    return await _maybe_await(
        get_document_content(
            document_id=document_id,
            page=page,
            dataset_id=dataset_id,
            account_id=account_id,
            max_chars=max_chars,
        )
    )


__all__ = ["keyword_search", "semantic_search", "chunk_read"]
