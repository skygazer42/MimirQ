"""
MCP tools for RAG workflows.

Provides common tools that can be used with MCP
or directly in RAG pipelines.

Usage:
    from app.rag.agents.tools.mcp_tools import (
        search_documents,
        get_document_content,
        calculate,
        get_current_time,
    )
"""

import ast
import asyncio
import contextlib
import logging
import math
import operator
import re
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.infrastructure.config import settings
from app.rag.agents.tools.mcp_client import (
    DocumentToolScope,
    MCPToolError,
    MCPToolRegistry,
    ToolParameter,
    get_mcp_registry,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.documents.records import Document as DBDocument
    from app.models.documents.records import DocumentChunk

logger = logging.getLogger("rag.tools.mcp_tools")

_NO_DOCUMENT_ACCESS_ERROR = "No document access"
_NUMBER_TOO_LARGE_ERROR = "Number too large"
_DATASET_ID_REQUIRED_ERROR = "dataset_id is required"
_DOCUMENT_NOT_FOUND_ERROR = "Document not found"
_DOCUMENT_STRUCTURE_SCHEMA = "mimirq.document_structure.v1"
_DATASET_ID_UUID_DESCRIPTION = "Dataset ID (UUID)"
_DOCUMENT_ID_UUID_DESCRIPTION = "Document ID (UUID)"

# Configuration
MCP_ENABLED = settings.MCP_ENABLED


@contextlib.contextmanager
def _db_session() -> Iterator["Session"]:
    # Helper kept at module scope so unit tests can monkeypatch it.
    from app.infrastructure.database.connection import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _require_document_scope(scope: DocumentToolScope | None) -> DocumentToolScope:
    if not isinstance(scope, DocumentToolScope) or not isinstance(scope.tenant_id, UUID):
        raise MCPToolError("Document tool scope with a tenant is required")
    if not isinstance(scope.account_id, str) or not scope.account_id.strip():
        raise MCPToolError("Document tool scope with an account is required")
    return scope


def _document_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error")
    if error is not None:
        raise MCPToolError(error)
    return result


def _search_document_scope(scope: DocumentToolScope, dataset_uuid: UUID) -> list[UUID] | None:
    import app.services.datasets.management as dataset_service
    from app.services.documents.read_scope import filter_allowed_document_ids

    with _db_session() as db:
        dataset = dataset_service.get_dataset(db, scope.tenant_id, dataset_uuid)
        dataset_service.assert_dataset_readable(db, dataset, scope.account_id)
        if scope.document_ids is None:
            return None
        return filter_allowed_document_ids(db, scope.tenant_id, scope.account_id, list(scope.document_ids))


# ============================================================================
# Document Tools
# ============================================================================


async def search_documents(
    query: str,
    top_k: int = 5,
    dataset_id: str | None = None,
    filter: dict[str, Any] | None = None,
    *,
    _scope: DocumentToolScope | None = None,
) -> dict[str, Any]:
    """
    Search documents in the knowledge base.

    Args:
        query: Search query
        top_k: Number of results
        dataset_id: Filter by dataset
        filter: Additional metadata filters

    Returns:
        Search results
    """
    try:
        from app.rag.retrieval.recall.retriever import hybrid_retriever

        scope = _require_document_scope(_scope)
        if dataset_id is None or not dataset_id.strip():
            raise MCPToolError(_DATASET_ID_REQUIRED_ERROR)
        try:
            dataset_uuid = UUID(str(dataset_id))
        except ValueError as error:
            raise MCPToolError("dataset_id must be a UUID") from error
        if scope.dataset_ids is not None and dataset_uuid not in scope.dataset_ids:
            raise MCPToolError("Dataset is outside the requested tool scope")
        document_ids = await asyncio.to_thread(_search_document_scope, scope, dataset_uuid)
        if document_ids == []:
            return {"query": query, "count": 0, "results": []}

        retriever = hybrid_retriever.model_copy(
            update={
                "k": int(top_k or 5),
                "dataset_id": dataset_uuid,
                "tenant_id": scope.tenant_id,
                "account_id": scope.account_id,
                "document_ids": document_ids,
                "metadata_filter": filter,
            }
        )
        documents = await retriever.ainvoke(query)

        results = []
        for doc in documents:
            content = doc.page_content
            metadata = doc.metadata
            results.append(
                {
                    "content": content[:500] + "..." if len(content) > 500 else content,
                    "document_id": metadata.get("document_id"),
                    "chunk_id": metadata.get("chunk_id") or metadata.get("id"),
                    "page": metadata.get("page"),
                    "source": metadata.get("source", "unknown"),
                    "score": metadata.get("score", 0),
                }
            )

        return {
            "query": query,
            "count": len(results),
            "results": results,
        }
    except MCPToolError:
        raise
    except Exception as e:
        logger.exception("Document search failed: %s", e)
        raise MCPToolError(str(e)) from e


def _document_content_error(document_id: str, page: int | None, error: str) -> dict[str, Any]:
    return {"document_id": document_id, "content": "", "page": page, "error": error}


def _document_content_ids(
    *,
    document_id: str,
    dataset_id: str | None,
    scope: DocumentToolScope | None,
) -> tuple[UUID, UUID, UUID]:
    scope = _require_document_scope(scope)
    if dataset_id is None or not dataset_id.strip():
        raise MCPToolError(_DATASET_ID_REQUIRED_ERROR)
    try:
        dataset_uuid = UUID(str(dataset_id))
    except ValueError as error:
        raise MCPToolError("dataset_id must be a UUID") from error
    try:
        document_uuid = UUID(str(document_id))
    except ValueError as error:
        raise MCPToolError("document_id must be a UUID") from error
    if scope.dataset_ids is not None and dataset_uuid not in scope.dataset_ids:
        raise MCPToolError("Dataset is outside the requested tool scope")
    if scope.document_ids is not None and document_uuid not in scope.document_ids:
        raise MCPToolError("Document is outside the requested tool scope")
    return dataset_uuid, document_uuid, scope.tenant_id


def _document_content_limit(max_chars: int) -> int:
    limit = int(max_chars or 0)
    return max(1_000, min(limit if limit > 0 else 50_000, 500_000))


def _load_scoped_document(
    db: "Session",
    document_model: "type[DBDocument]",
    *,
    document_id: UUID,
    tenant_id: UUID,
    dataset_id: UUID,
) -> "DBDocument | None":
    document = (
        db.query(document_model)
        .filter(
            document_model.id == document_id,
            document_model.tenant_id == tenant_id,
            document_model.disabled_at.is_(None),
        )
        .first()
    )
    if document is None or document.dataset_id != dataset_id:
        return None
    return document


def _can_read_document_content(
    db: "Session",
    *,
    tenant_id: UUID,
    document_id: UUID,
    account_id: str | None,
) -> bool:
    from app.services.documents.read_scope import get_allowed_document_id_sets

    if account_id is None or not account_id.strip():
        return False
    allowed, _missing = get_allowed_document_id_sets(db, tenant_id, account_id, [document_id])
    return document_id in allowed


def _load_document_content_chunks(
    db: "Session",
    chunk_model: "type[DocumentChunk]",
    *,
    tenant_id: UUID,
    document_id: UUID,
    active_key: str | None,
) -> list["DocumentChunk"]:
    query = (
        db.query(chunk_model)
        .filter(
            chunk_model.tenant_id == tenant_id,
            chunk_model.document_id == document_id,
            chunk_model.disabled_at.is_(None),
        )
        .order_by(chunk_model.chunk_index.asc(), chunk_model.id.asc())
    )
    if not active_key:
        return list(query.all())
    active_chunks = query.filter(
        chunk_model.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
    ).all()
    return list(active_chunks or query.all())


def _filter_document_chunks_by_page(
    chunks: list["DocumentChunk"],
    page: int | None,
) -> list["DocumentChunk"] | None:
    if page is None:
        return chunks
    if isinstance(page, bool):
        return None
    try:
        page_number = int(page)
    except (OverflowError, TypeError, ValueError):
        return None
    return [chunk for chunk in chunks if chunk.page_number == page_number]


def _assemble_document_content(
    chunks: list["DocumentChunk"],
    *,
    max_chars: int,
) -> tuple[str, int, list[int], bool]:
    parts: list[str] = []
    total = 0
    truncated = False
    pages: list[int] = []
    for chunk in chunks:
        text = chunk.content
        if not text.strip():
            continue
        separator = "\n\n" if parts else ""
        remaining = max_chars - total - len(separator)
        if remaining <= 0:
            truncated = True
            break
        clipped = len(text) > remaining
        parts.append(separator + (text[:remaining] if clipped else text))
        total += len(separator) + (remaining if clipped else len(text))
        if chunk.page_number is not None:
            pages.append(chunk.page_number)
        if clipped:
            truncated = True
            break
    return "".join(parts), len(parts), pages, truncated


def _load_scoped_document_content_chunks(
    db: "Session",
    *,
    document_id: str,
    document_uuid: UUID,
    dataset_uuid: UUID,
    tenant_uuid: UUID,
    page: int | None,
    account_id: str | None,
) -> "tuple[DBDocument, list[DocumentChunk]] | dict[str, Any]":
    from app.models.documents.records import Document as DBDocument
    from app.models.documents.records import DocumentChunk
    from app.services.documents.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash

    document = _load_scoped_document(
        db,
        DBDocument,
        document_id=document_uuid,
        tenant_id=tenant_uuid,
        dataset_id=dataset_uuid,
    )
    if document is None:
        return _document_content_error(document_id, page, _DOCUMENT_NOT_FOUND_ERROR)
    if not _can_read_document_content(
        db,
        tenant_id=tenant_uuid,
        document_id=document_uuid,
        account_id=account_id,
    ):
        return _document_content_error(document_id, page, _NO_DOCUMENT_ACCESS_ERROR)
    active_hash = get_active_pipeline_hash(document.doc_metadata)
    active_key = build_doc_pipeline_key(document_uuid, active_hash) if active_hash else None
    chunks = _load_document_content_chunks(
        db,
        DocumentChunk,
        tenant_id=tenant_uuid,
        document_id=document_uuid,
        active_key=active_key,
    )
    chunks = _filter_document_chunks_by_page(chunks, page)
    if chunks is None:
        return _document_content_error(document_id, page, "page must be an integer")
    return document, chunks


def _build_document_content_result(
    document: "DBDocument",
    chunks: list["DocumentChunk"],
    *,
    document_id: str,
    dataset_uuid: UUID,
    page: int | None,
    max_chars: int,
) -> dict[str, Any]:
    content, returned_chunks, pages, truncated = _assemble_document_content(chunks, max_chars=max_chars)
    return {
        "document_id": document_id,
        "dataset_id": str(dataset_uuid),
        "filename": document.filename,
        "file_type": document.file_type,
        "page": page,
        "chunk_count": len(chunks),
        "returned_chunks": returned_chunks,
        "pages": sorted(set(pages)),
        "truncated": truncated,
        "content": content,
    }


def _get_document_content_sync(
    document_id: str,
    page: int | None = None,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    try:
        scope = _require_document_scope(_scope)
        dataset_uuid, document_uuid, tenant_uuid = _document_content_ids(
            document_id=document_id,
            dataset_id=dataset_id,
            scope=scope,
        )
        with _db_session() as db:
            loaded = _load_scoped_document_content_chunks(
                db,
                document_id=document_id,
                document_uuid=document_uuid,
                tenant_uuid=tenant_uuid,
                dataset_uuid=dataset_uuid,
                page=page,
                account_id=scope.account_id,
            )
            if isinstance(loaded, dict):
                return loaded
            document, chunks = loaded
            return _build_document_content_result(
                document,
                chunks,
                document_id=document_id,
                dataset_uuid=dataset_uuid,
                page=page,
                max_chars=_document_content_limit(max_chars),
            )
    except Exception as exc:
        logger.exception("Failed to get document: %s", exc)
        return {"document_id": document_id, "error": str(exc)}


async def get_document_content(
    document_id: str,
    page: int | None = None,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    """
    Get full content of a document.

    Args:
        document_id: Document ID
        page: Optional page number

    Returns:
        Document content
    """
    result = await asyncio.to_thread(
        _get_document_content_sync,
        document_id,
        page,
        dataset_id=dataset_id,
        _scope=_scope,
        max_chars=max_chars,
    )
    return _document_tool_result(result)


def _get_document_sync(
    document_id: str,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
) -> dict[str, Any]:
    try:
        from app.models.documents.records import Document as DBDocument

        scope = _require_document_scope(_scope)
        ds_uuid, doc_uuid, tenant_uuid = _document_content_ids(
            document_id=document_id, dataset_id=dataset_id, scope=scope
        )

        with _db_session() as db:
            document = (
                db.query(DBDocument)
                .filter(
                    DBDocument.id == doc_uuid,
                    DBDocument.tenant_id == tenant_uuid,
                    DBDocument.dataset_id == ds_uuid,
                    DBDocument.disabled_at.is_(None),
                )
                .first()
            )
            if not document:
                return {"document_id": document_id, "error": _DOCUMENT_NOT_FOUND_ERROR}

            if not _can_read_document_content(
                db, tenant_id=tenant_uuid, document_id=doc_uuid, account_id=scope.account_id
            ):
                return {"document_id": document_id, "error": _NO_DOCUMENT_ACCESS_ERROR}

            meta = document.doc_metadata
            meta = meta if isinstance(meta, dict) else {}
            return {
                "document_id": str(document.id),
                "dataset_id": str(ds_uuid),
                "filename": document.filename,
                "file_type": document.file_type,
                "chunk_count": document.chunk_count or 0,
                "total_characters": document.total_characters or 0,
                "page_count": meta.get("page_count"),
                "description": meta.get("doc_description") or meta.get("description"),
            }
    except Exception as e:
        logger.exception("Failed to get document info: %s", e)
        return {"document_id": document_id, "error": str(e)}


async def get_document(
    document_id: str,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
) -> dict[str, Any]:
    """Get bounded document metadata for tool-agent style retrieval."""
    result = await asyncio.to_thread(_get_document_sync, document_id, dataset_id=dataset_id, _scope=_scope)
    return _document_tool_result(result)


def _get_document_structure_sync(
    document_id: str,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    try:
        from app.rag.retrieval.evidence.document_structure import load_document_structure

        scope = _require_document_scope(_scope)
        ds_uuid, doc_uuid, tenant_uuid = _document_content_ids(
            document_id=document_id, dataset_id=dataset_id, scope=scope
        )

        with _db_session() as db:
            return load_document_structure(
                db=db,
                tenant_id=tenant_uuid,
                account_id=scope.account_id,
                dataset_id=ds_uuid,
                document_id=doc_uuid,
                max_nodes=max_nodes,
            )
    except Exception as e:
        logger.exception("Failed to get document structure: %s", e)
        return {
            "schema": _DOCUMENT_STRUCTURE_SCHEMA,
            "document": {"document_id": document_id},
            "nodes": [],
            "error": str(e),
        }


async def get_document_structure(
    document_id: str,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Get PageIndex-style section structure derived from existing hierarchy metadata."""
    result = await asyncio.to_thread(
        _get_document_structure_sync,
        document_id,
        dataset_id=dataset_id,
        _scope=_scope,
        max_nodes=max_nodes,
    )
    return _document_tool_result(result)


def _page_number(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        logging.getLogger("app.rag.tools.mcp_tools").debug("Skipping item after non-critical exception", exc_info=True)
        return None


def _page_token_values(token: str) -> list[int]:
    if not token:
        return []
    if "-" not in token:
        value = _page_number(token)
        return [value] if value is not None and value > 0 else []
    left, right = token.split("-", 1)
    start = _page_number(left)
    end = _page_number(right)
    if start is None or end is None or start <= 0 or end <= 0:
        return []
    lower, upper = sorted((start, end))
    return list(range(lower, min(upper, lower + 99) + 1))


def _parse_pages_selector(pages: Any) -> list[int]:
    if pages is None:
        return []
    if isinstance(pages, bool):
        return []
    if isinstance(pages, int):
        return [pages] if pages > 0 else []
    raw = str(pages).strip()
    if not raw:
        return []
    pages_set: set[int] = set()
    for part in raw.split(","):
        pages_set.update(_page_token_values(part.strip()))
    return sorted(pages_set)[:100]


def _get_page_content_sync(
    document_id: str,
    pages: Any,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    selected_pages = _parse_pages_selector(pages)
    if not selected_pages:
        return {"document_id": document_id, "pages_requested": [], "error": "pages must select positive page numbers"}

    parts: list[str] = []
    returned_chunks = 0
    truncated = False
    remaining = max(1_000, min(int(max_chars or 50_000), 500_000))
    last: dict[str, Any] = {"document_id": document_id, "dataset_id": dataset_id}
    for page in selected_pages:
        prefix = f"\n\n[page {page}]\n" if parts else f"[page {page}]\n"
        content_limit = remaining - len(prefix)
        if content_limit <= 0:
            truncated = True
            break
        try:
            scope = _require_document_scope(_scope)
            dataset_uuid, document_uuid, tenant_uuid = _document_content_ids(
                document_id=document_id, dataset_id=dataset_id, scope=scope
            )
            with _db_session() as db:
                loaded = _load_scoped_document_content_chunks(
                    db,
                    document_id=document_id,
                    document_uuid=document_uuid,
                    dataset_uuid=dataset_uuid,
                    tenant_uuid=tenant_uuid,
                    page=page,
                    account_id=scope.account_id,
                )
                if isinstance(loaded, dict):
                    return {**loaded, "pages_requested": selected_pages}
                document, chunks = loaded
                result = _build_document_content_result(
                    document,
                    chunks,
                    document_id=document_id,
                    dataset_uuid=dataset_uuid,
                    page=page,
                    max_chars=content_limit,
                )
        except Exception as exc:
            logger.exception("Failed to get document: %s", exc)
            return {"document_id": document_id, "error": str(exc), "pages_requested": selected_pages}
        last = result
        text = result["content"]
        if text.strip():
            parts.append(prefix + text)
            remaining -= len(prefix) + len(text)
            returned_chunks += result["returned_chunks"]
        if result["truncated"]:
            truncated = True
            break

    return {
        "document_id": document_id,
        "dataset_id": dataset_id,
        "filename": last.get("filename"),
        "file_type": last.get("file_type"),
        "pages_requested": selected_pages,
        "pages": selected_pages,
        "returned_chunks": returned_chunks,
        "truncated": truncated,
        "content": "".join(parts),
    }


async def get_page_content(
    document_id: str,
    pages: Any,
    *,
    dataset_id: str | None = None,
    _scope: DocumentToolScope | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    """Get page-range content for PageIndex-style tool-agent retrieval."""
    result = await asyncio.to_thread(
        _get_page_content_sync,
        document_id,
        pages,
        dataset_id=dataset_id,
        _scope=_scope,
        max_chars=max_chars,
    )
    return _document_tool_result(result)


# ============================================================================
# Utility Tools
# ============================================================================


_MAX_MATH_EXPRESSION_CHARS = 256
_MAX_MATH_AST_NODES = 200
_MAX_MATH_INT_BITS = 4096
_MAX_MATH_POW_ABS_EXP = 4096


class _SafeMathEvaluator:
    def __init__(self, allowed_names: dict[str, Any]) -> None:
        self.allowed_names = allowed_names
        self.node_count = 0

    def _bump(self) -> None:
        self.node_count += 1
        if self.node_count > _MAX_MATH_AST_NODES:
            raise ValueError("Expression too complex")

    @staticmethod
    def _ensure_number_safe(value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Number must be finite")
        if isinstance(value, int) and value.bit_length() > _MAX_MATH_INT_BITS:
            raise ValueError(_NUMBER_TOO_LARGE_ERROR)

    @staticmethod
    def _validate_pow_exponent(base: Any, exponent: Any) -> None:
        if not isinstance(exponent, int):
            return
        if abs(exponent) > _MAX_MATH_POW_ABS_EXP:
            raise ValueError("Exponent too large")
        if isinstance(base, int) and exponent >= 0 and base not in (0, 1, -1):
            estimated_bits = abs(exponent) * max(1, base.bit_length())
            if estimated_bits > _MAX_MATH_INT_BITS:
                raise ValueError(_NUMBER_TOO_LARGE_ERROR)

    def _safe_pow(self, base: Any, exponent: Any, modulus: Any | None = None) -> Any:
        if any(isinstance(value, bool) for value in (base, exponent, modulus)):
            raise ValueError("Invalid number")
        self._validate_pow_exponent(base, exponent)
        if modulus is None:
            result = base**exponent
        else:
            if not all(isinstance(value, int) for value in (base, exponent, modulus)):
                raise ValueError("pow(a, b, mod) only supports integers")
            if modulus == 0:
                raise ValueError("Modulo cannot be zero")
            result = pow(base, exponent, modulus)
        self._ensure_number_safe(result)
        return result

    def _expression(self, node: ast.Expression) -> Any:
        return self.evaluate(node.body)

    def _constant(self, node: ast.Constant) -> Any:
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ValueError("Only numbers are allowed")
        self._ensure_number_safe(node.value)
        return node.value

    def _unary(self, node: ast.UnaryOp) -> Any:
        operation = {ast.UAdd: operator.pos, ast.USub: operator.neg}.get(type(node.op))
        if operation is None:
            raise ValueError("Unsupported unary operator")
        result = operation(self.evaluate(node.operand))
        self._ensure_number_safe(result)
        return result

    @staticmethod
    def _safe_multiply(left: Any, right: Any) -> Any:
        if isinstance(left, int) and isinstance(right, int):
            if left.bit_length() + right.bit_length() > _MAX_MATH_INT_BITS:
                raise ValueError(_NUMBER_TOO_LARGE_ERROR)
        return left * right

    def _binary(self, node: ast.BinOp) -> Any:
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            return self._safe_pow(left, right)
        operations = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: self._safe_multiply,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
        }
        operation = operations.get(type(node.op))
        if operation is None:
            raise ValueError("Unsupported operator")
        result = operation(left, right)
        self._ensure_number_safe(result)
        return result

    def _name(self, node: ast.Name) -> Any:
        if node.id not in self.allowed_names:
            raise ValueError(f"Unknown name: {node.id}")
        value = self.allowed_names[node.id]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self._ensure_number_safe(value)
            return value
        raise ValueError(f"'{node.id}' must be called as a function")

    def _call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed")
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed")
        name = node.func.id
        function = self.allowed_names.get(name)
        if function is None or not callable(function):
            raise ValueError(f"Unknown function: {name}")
        arguments = [self.evaluate(argument) for argument in node.args]
        if name == "pow":
            if len(arguments) not in (2, 3):
                raise ValueError("pow() expects 2 or 3 arguments")
            return self._safe_pow(
                arguments[0],
                arguments[1],
                arguments[2] if len(arguments) == 3 else None,
            )
        result = function(*arguments)
        self._ensure_number_safe(result)
        return result

    def _sequence(self, node: ast.Tuple | ast.List) -> list[Any]:
        return [self.evaluate(element) for element in node.elts]

    def evaluate(self, node: ast.AST) -> Any:
        self._bump()
        handlers = {
            ast.Expression: self._expression,
            ast.Constant: self._constant,
            ast.UnaryOp: self._unary,
            ast.BinOp: self._binary,
            ast.Name: self._name,
            ast.Call: self._call,
            ast.Tuple: self._sequence,
            ast.List: self._sequence,
        }
        handler = handlers.get(type(node))
        if handler is None:
            raise ValueError("Unsupported expression")
        return handler(node)


def _safe_eval_math(expression: str, allowed_names: dict[str, Any]) -> Any:
    expr = (expression).strip().lower()
    if not expr:
        raise ValueError("Empty expression")
    if len(expr) > _MAX_MATH_EXPRESSION_CHARS:
        raise ValueError("Expression too long")
    tree = ast.parse(expr.replace("^", "**"), mode="eval")
    return _SafeMathEvaluator(allowed_names).evaluate(tree)


def _resolve_timezone(name: str | None) -> tzinfo:
    raw = name.strip() if name is not None else None
    if not raw:
        return UTC
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def get_current_time(
    format: str = "%Y-%m-%d %H:%M:%S",
    timezone: str | None = None,
) -> dict[str, str]:
    """
    Get current date and time.

    Args:
        format: DateTime format string
        timezone: Optional timezone name

    Returns:
        Formatted time information
    """
    now = datetime.now(_resolve_timezone(timezone))

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekdays_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    return {
        "datetime": now.strftime(format),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekdays[now.weekday()],
        "weekday_cn": weekdays_cn[now.weekday()],
        "timestamp": str(int(now.timestamp())),
    }


def calculate(expression: str) -> dict[str, Any]:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: Mathematical expression

    Returns:
        Calculation result
    """
    allowed_names = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "pi": math.pi,
        "e": math.e,
    }

    try:
        result = _safe_eval_math(expression, allowed_names)

        return {
            "expression": expression,
            "result": result,
            "success": True,
        }
    except Exception as e:
        raise MCPToolError(str(e)) from e


def format_number(
    number: float,
    decimals: int = 2,
    thousands_separator: bool = True,
) -> dict[str, str | bool]:
    """
    Format a number for display.

    Args:
        number: Number to format
        decimals: Decimal places
        thousands_separator: Use thousands separator

    Returns:
        Formatted number
    """
    try:
        if thousands_separator:
            formatted = f"{number:,.{decimals}f}"
        else:
            formatted = f"{number:.{decimals}f}"
    except (TypeError, ValueError, OverflowError) as exc:
        return {
            "original": str(number),
            "formatted": str(number),
            "success": False,
            "error": str(exc),
        }
    return {
        "original": str(number),
        "formatted": formatted,
        "success": True,
    }


def convert_units(
    value: float,
    from_unit: str,
    to_unit: str,
) -> dict[str, Any]:
    """
    Convert between units.

    Args:
        value: Value to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Conversion result
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MCPToolError("Unit conversion value must be a finite number")
    # Unit conversion factors (to base unit)
    conversions = {
        # Length (to meters)
        "m": 1,
        "km": 1000,
        "cm": 0.01,
        "mm": 0.001,
        "mi": 1609.34,
        "ft": 0.3048,
        "in": 0.0254,
        # Weight (to kilograms)
        "kg": 1,
        "g": 0.001,
        "mg": 0.000001,
        "lb": 0.453592,
        "oz": 0.0283495,
        # Temperature (special handling)
        "c": "celsius",
        "f": "fahrenheit",
        "k": "kelvin",
    }

    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    # Handle temperature separately
    if from_unit in ("c", "f", "k") or to_unit in ("c", "f", "k"):
        try:
            result = _convert_temperature(value, from_unit, to_unit)
            return {
                "value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "result": result,
                "success": True,
            }
        except Exception as e:
            raise MCPToolError(str(e)) from e

    if from_unit not in conversions or to_unit not in conversions:
        raise MCPToolError("Unknown unit")

    length_units = {"m", "km", "cm", "mm", "mi", "ft", "in"}
    if (from_unit in length_units) != (to_unit in length_units):
        raise MCPToolError("Units must have the same dimension")

    # Convert through base unit
    base_value = value * conversions[from_unit]
    result = base_value / conversions[to_unit]

    return {
        "value": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "result": result,
        "success": True,
    }


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperature between units."""
    # Convert to Celsius first
    if from_unit == "c":
        celsius = value
    elif from_unit == "f":
        celsius = (value - 32) * 5 / 9
    elif from_unit == "k":
        celsius = value - 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")

    # Convert from Celsius to target
    if to_unit == "c":
        return celsius
    elif to_unit == "f":
        return celsius * 9 / 5 + 32
    elif to_unit == "k":
        return celsius + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {to_unit}")


# ============================================================================
# Text Tools
# ============================================================================


def count_text(text: str) -> dict[str, int]:
    """
    Count characters, words, and lines in text.

    Args:
        text: Text to analyze

    Returns:
        Count statistics
    """
    lines = text.split("\n")
    words = text.split()

    return {
        "characters": len(text),
        "characters_no_spaces": len(text.replace(" ", "").replace("\n", "")),
        "words": len(words),
        "lines": len(lines),
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
    }


def extract_keywords(
    text: str,
    max_keywords: int = 10,
) -> dict[str, Any]:
    """
    Extract keywords from text (simple frequency-based).

    Args:
        text: Text to analyze
        max_keywords: Maximum keywords to return

    Returns:
        Extracted keywords
    """
    # Simple word frequency
    words = re.findall(r"\b[a-zA-Z\u4e00-\u9fa5]+\b", text.lower())

    # Filter stop words (basic)
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "and",
        "but",
        "if",
        "or",
        "because",
        "until",
        "while",
        "although",
        "though",
        "的",
        "是",
        "在",
        "有",
        "和",
        "与",
        "了",
        "不",
        "人",
        "我",
        "他",
        "她",
        "它",
        "们",
        "这",
        "那",
        "就",
        "也",
        "都",
        "而",
        "及",
        "着",
        "或",
        "把",
        "被",
        "让",
        "给",
        "到",
        "从",
        "向",
    }

    filtered = [w for w in words if w not in stop_words and len(w) > 1]

    # Count frequencies
    freq = {}
    for word in filtered:
        freq[word] = freq.get(word, 0) + 1

    # Sort by frequency
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    keywords = sorted_words[:max_keywords]

    return {
        "keywords": [{"word": w, "count": c} for w, c in keywords],
        "total_words": len(words),
        "unique_words": len(set(words)),
    }


# ============================================================================
# Tool Registration
# ============================================================================


def register_default_tools(registry: MCPToolRegistry | None = None) -> MCPToolRegistry:
    """
    Register default tools with the registry.

    Args:
        registry: Optional registry instance

    Returns:
        Registry with tools registered
    """
    if registry is None:
        registry = get_mcp_registry()

    # Document tools
    registry.register(
        name="search_documents",
        func=search_documents,
        scope_arg="_scope",
        description="Search documents in the knowledge base",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query", required=True),
            ToolParameter(name="top_k", type="integer", description="Number of results", default=5),
            ToolParameter(name="dataset_id", type="string", description=_DATASET_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="filter", type="object", description="Optional metadata filter", default=None),
        ],
    )

    registry.register(
        name="get_document_content",
        func=get_document_content,
        scope_arg="_scope",
        description="Get full content of a document (assembled from chunks)",
        parameters=[
            ToolParameter(name="document_id", type="string", description=_DOCUMENT_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="dataset_id", type="string", description=_DATASET_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="page", type="integer", description="Optional page number", default=None),
            ToolParameter(name="max_chars", type="integer", description="Max characters to return", default=50000),
        ],
    )

    registry.register(
        name="get_document",
        func=get_document,
        scope_arg="_scope",
        description="Get bounded document metadata",
        parameters=[
            ToolParameter(name="document_id", type="string", description=_DOCUMENT_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="dataset_id", type="string", description=_DATASET_ID_UUID_DESCRIPTION, required=True),
        ],
    )

    registry.register(
        name="get_document_structure",
        func=get_document_structure,
        scope_arg="_scope",
        description="Get document section structure from existing hierarchy metadata",
        parameters=[
            ToolParameter(name="document_id", type="string", description=_DOCUMENT_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="dataset_id", type="string", description=_DATASET_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="max_nodes", type="integer", description="Max structure nodes", default=200),
        ],
    )

    registry.register(
        name="get_page_content",
        func=get_page_content,
        scope_arg="_scope",
        description="Get page or page-range content for document-structure navigation",
        parameters=[
            ToolParameter(name="document_id", type="string", description=_DOCUMENT_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(
                name="pages", type="string", description="Page selector, e.g. '3', '5-7', or '3,8'", required=True
            ),
            ToolParameter(name="dataset_id", type="string", description=_DATASET_ID_UUID_DESCRIPTION, required=True),
            ToolParameter(name="max_chars", type="integer", description="Max characters to return", default=50000),
        ],
    )

    # Utility tools
    registry.register(
        name="get_current_time",
        func=get_current_time,
        description="Get current date and time",
        parameters=[
            ToolParameter(name="format", type="string", description="DateTime format", default="%Y-%m-%d %H:%M:%S"),
        ],
    )

    registry.register(
        name="calculate",
        func=calculate,
        description="Evaluate a mathematical expression",
        parameters=[
            ToolParameter(name="expression", type="string", description="Math expression", required=True),
        ],
    )

    registry.register(
        name="convert_units",
        func=convert_units,
        description="Convert between units",
        parameters=[
            ToolParameter(name="value", type="number", description="Value to convert", required=True),
            ToolParameter(name="from_unit", type="string", description="Source unit", required=True),
            ToolParameter(name="to_unit", type="string", description="Target unit", required=True),
        ],
    )

    # Text tools
    registry.register(
        name="count_text",
        func=count_text,
        description="Count characters, words, and lines in text",
        parameters=[
            ToolParameter(name="text", type="string", description="Text to analyze", required=True),
        ],
    )

    registry.register(
        name="extract_keywords",
        func=extract_keywords,
        description="Extract keywords from text",
        parameters=[
            ToolParameter(name="text", type="string", description="Text to analyze", required=True),
            ToolParameter(name="max_keywords", type="integer", description="Max keywords", default=10),
        ],
    )

    logger.info("Registered %d default tools", 10)
    return registry


# Initialize default tools on import if MCP is enabled
if MCP_ENABLED:
    try:
        register_default_tools()
    except Exception as e:
        logger.warning("Failed to register default tools: %s", e)
