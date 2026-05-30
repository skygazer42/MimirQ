"""
MCP tools for RAG workflows.

Provides common tools that can be used with MCP
or directly in RAG pipelines.

Usage:
    from app.rag.tools.mcp_tools import (
        search_documents,
        get_document_content,
        calculate,
        get_current_time,
    )
"""

import ast
import asyncio
import contextlib
import math
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.tools.mcp_client import (
    MCPToolRegistry,
    ToolParameter,
    get_mcp_registry,
)

logger = get_logger("rag.tools.mcp_tools")

_NO_DOCUMENT_ACCESS_ERROR = "No document access"
_NUMBER_TOO_LARGE_ERROR = "Number too large"

# Configuration
MCP_ENABLED = getattr(settings, "MCP_ENABLED", False)

@contextlib.contextmanager
def _db_session() -> Iterator[Any]:
    # Helper kept at module scope so unit tests can monkeypatch it.
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _document_permission_exists(
    db: Any,
    *,
    tenant_id: UUID,
    document_id: UUID,
    account_id: str,
) -> bool:
    from app.models.document import DocumentPermission

    if not account_id:
        return False
    exists = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document_id,
            DocumentPermission.account_id == account_id,
        )
        .first()
    )
    return bool(exists)


# ============================================================================
# Document Tools
# ============================================================================


async def search_documents(
    query: str,
    top_k: int = 5,
    dataset_id: str | None = None,
    filter: dict[str, Any] | None = None,
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
        from app.rag.retriever import hybrid_retriever

        if dataset_id is None or not str(dataset_id).strip():
            return {
                "query": query,
                "count": 0,
                "results": [],
                "error": "dataset_id is required",
            }
        try:
            dataset_uuid = UUID(str(dataset_id))
        except Exception:
            return {
                "query": query,
                "count": 0,
                "results": [],
                "error": "dataset_id must be a UUID",
            }

        retriever = hybrid_retriever.model_copy(
            update={
                "k": int(top_k or 5),
                "dataset_id": dataset_uuid,
                "metadata_filter": filter,
            }
        )
        documents = await retriever.ainvoke(query)

        results = []
        for doc in documents:
            content = doc.page_content if hasattr(doc, "page_content") else doc.get("content", "")
            metadata = doc.metadata if hasattr(doc, "metadata") else doc.get("metadata", {})
            results.append({
                "content": content[:500] + "..." if len(content) > 500 else content,
                "document_id": metadata.get("document_id"),
                "chunk_id": metadata.get("chunk_id") or metadata.get("id"),
                "page": metadata.get("page"),
                "source": metadata.get("source", "unknown"),
                "score": metadata.get("score", 0),
            })

        return {
            "query": query,
            "count": len(results),
            "results": results,
        }
    except Exception as e:
        logger.exception("Document search failed: %s", e)
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": str(e),
        }


def _get_document_content_sync(
    document_id: str,
    page: int | None = None,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    try:
        from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
        from app.models.document import Document as DBDocument
        from app.models.document import DocumentChunk

        if dataset_id is None or not str(dataset_id).strip():
            return {
                "document_id": document_id,
                "content": "",
                "page": page,
                "error": "dataset_id is required",
            }
        try:
            ds_uuid = UUID(str(dataset_id))
        except Exception:
            return {
                "document_id": document_id,
                "content": "",
                "page": page,
                "error": "dataset_id must be a UUID",
            }

        try:
            doc_uuid = UUID(str(document_id))
        except Exception:
            return {
                "document_id": document_id,
                "content": "",
                "page": page,
                "error": "document_id must be a UUID",
            }

        try:
            tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip())
        except Exception:
            # Should never happen; keep the failure explicit.
            return {
                "document_id": document_id,
                "content": "",
                "page": page,
                "error": "DEFAULT_TENANT_ID is invalid",
            }

        max_chars = int(max_chars or 0)
        if max_chars <= 0:
            max_chars = 50_000
        max_chars = max(1_000, min(max_chars, 500_000))

        with _db_session() as db:
            document = (
                db.query(DBDocument)
                .filter(
                    DBDocument.id == doc_uuid,
                    DBDocument.tenant_id == tenant_uuid,
                    DBDocument.disabled_at.is_(None),
                )
                .first()
            )
            if not document:
                return {
                    "document_id": document_id,
                    "content": "",
                    "page": page,
                    "error": "Document not found",
                }

            # Fail closed: the caller must operate within the dataset scope they searched.
            if getattr(document, "dataset_id", None) != ds_uuid:
                return {
                    "document_id": document_id,
                    "content": "",
                    "page": page,
                    "error": "Document not found",
                }

            # Best-effort document-level ACL trimming when account_id is provided.
            mode = str(getattr(document, "access_mode", "") or "").strip().lower()
            owner = str(getattr(document, "owner_id", "") or "").strip()
            if account_id:
                actor = str(account_id or "").strip()
                is_owner = bool(owner and owner == actor)
                if mode and mode not in {"inherit", "all_team_members"} and not is_owner:
                    if mode == "only_me":
                        return {
                            "document_id": document_id,
                            "content": "",
                            "page": page,
                            "error": _NO_DOCUMENT_ACCESS_ERROR,
                        }
                    if mode == "partial_members":
                        if not _document_permission_exists(
                            db,
                            tenant_id=tenant_uuid,
                            document_id=doc_uuid,
                            account_id=actor,
                        ):
                            return {
                                "document_id": document_id,
                                "content": "",
                                "page": page,
                                "error": _NO_DOCUMENT_ACCESS_ERROR,
                            }
                    else:
                        return {
                            "document_id": document_id,
                            "content": "",
                            "page": page,
                            "error": _NO_DOCUMENT_ACCESS_ERROR,
                        }

            # Scope to active pipeline version when available; fall back to legacy chunks if absent.
            active_hash = get_active_pipeline_hash(getattr(document, "doc_metadata", None))
            active_key = build_doc_pipeline_key(doc_uuid, active_hash) if active_hash else None

            q = (
                db.query(DocumentChunk)
                .filter(
                    DocumentChunk.tenant_id == tenant_uuid,
                    DocumentChunk.document_id == doc_uuid,
                    DocumentChunk.disabled_at.is_(None),
                )
                .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
            )
            if active_key:
                q_active = q.filter(
                    DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
                )
                chunks = q_active.all()
                if not chunks:
                    chunks = q.all()
            else:
                chunks = q.all()

            if page is not None:
                try:
                    page_int = int(page)
                except Exception:
                    return {
                        "document_id": document_id,
                        "content": "",
                        "page": page,
                        "error": "page must be an integer",
                    }
                chunks = [c for c in chunks if int(getattr(c, "page_number", -1) or -1) == page_int]

            # Assemble content with a hard cap to avoid exploding tool payload size.
            parts: list[str] = []
            total = 0
            truncated = False
            returned_chunks = 0
            pages: list[int] = []
            for c in chunks:
                text = str(getattr(c, "content", "") or "")
                if not text.strip():
                    continue
                sep = "\n\n" if parts else ""
                remaining = max_chars - total - len(sep)
                if remaining <= 0:
                    truncated = True
                    break
                if len(text) > remaining:
                    parts.append(sep + text[:remaining])
                    total += len(sep) + remaining
                    truncated = True
                    returned_chunks += 1
                    if getattr(c, "page_number", None) is not None:
                        pages.append(int(c.page_number))
                    break
                parts.append(sep + text)
                total += len(sep) + len(text)
                returned_chunks += 1
                if getattr(c, "page_number", None) is not None:
                    pages.append(int(c.page_number))

            content = "".join(parts)
        return {
            "document_id": document_id,
            "dataset_id": str(ds_uuid),
            "filename": str(getattr(document, "filename", "") or ""),
            "file_type": str(getattr(document, "file_type", "") or ""),
            "page": page,
            "chunk_count": int(len(chunks)),
            "returned_chunks": int(returned_chunks),
            "pages": sorted(set(pages)),
            "truncated": bool(truncated),
            "content": content,
        }
    except Exception as e:
        logger.exception("Failed to get document: %s", e)
        return {
            "document_id": document_id,
            "error": str(e),
        }


async def get_document_content(
    document_id: str,
    page: int | None = None,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
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
    return await asyncio.to_thread(
        _get_document_content_sync,
        document_id,
        page,
        dataset_id=dataset_id,
        account_id=account_id,
        max_chars=max_chars,
    )


def _get_document_sync(
    document_id: str,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    try:
        from app.models.document import Document as DBDocument

        if dataset_id is None or not str(dataset_id).strip():
            return {"document_id": document_id, "error": "dataset_id is required"}
        try:
            ds_uuid = UUID(str(dataset_id))
            doc_uuid = UUID(str(document_id))
            tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip())
        except Exception:
            return {"document_id": document_id, "error": "dataset_id/document_id/DEFAULT_TENANT_ID must be UUIDs"}

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
                return {"document_id": document_id, "error": "Document not found"}

            mode = str(getattr(document, "access_mode", "") or "").strip().lower()
            owner = str(getattr(document, "owner_id", "") or "").strip()
            if account_id:
                actor = str(account_id or "").strip()
                is_owner = bool(owner and owner == actor)
                if mode and mode not in {"inherit", "all_team_members"} and not is_owner:
                    if mode == "only_me":
                        return {"document_id": document_id, "error": _NO_DOCUMENT_ACCESS_ERROR}
                    if mode == "partial_members" and not _document_permission_exists(
                        db,
                        tenant_id=tenant_uuid,
                        document_id=doc_uuid,
                        account_id=actor,
                    ):
                        return {"document_id": document_id, "error": _NO_DOCUMENT_ACCESS_ERROR}

            meta = getattr(document, "doc_metadata", None)
            meta = meta if isinstance(meta, dict) else {}
            return {
                "document_id": str(document.id),
                "dataset_id": str(ds_uuid),
                "filename": str(getattr(document, "filename", "") or ""),
                "file_type": str(getattr(document, "file_type", "") or ""),
                "chunk_count": int(getattr(document, "chunk_count", 0) or 0),
                "total_characters": int(getattr(document, "total_characters", 0) or 0),
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
    account_id: str | None = None,
) -> dict[str, Any]:
    """Get bounded document metadata for tool-agent style retrieval."""
    return await asyncio.to_thread(_get_document_sync, document_id, dataset_id=dataset_id, account_id=account_id)


def _get_document_structure_sync(
    document_id: str,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    try:
        from app.rag.retrieval.document_structure import load_document_structure

        if dataset_id is None or not str(dataset_id).strip():
            return {"schema": "mimirq.document_structure.v1", "document": {"document_id": document_id}, "nodes": [], "error": "dataset_id is required"}
        try:
            ds_uuid = UUID(str(dataset_id))
            doc_uuid = UUID(str(document_id))
            tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip())
        except Exception:
            return {
                "schema": "mimirq.document_structure.v1",
                "document": {"document_id": document_id},
                "nodes": [],
                "error": "dataset_id/document_id/DEFAULT_TENANT_ID must be UUIDs",
            }

        with _db_session() as db:
            return load_document_structure(
                db=db,
                tenant_id=tenant_uuid,
                account_id=str(account_id or ""),
                dataset_id=ds_uuid,
                document_id=doc_uuid,
                max_nodes=max_nodes,
            )
    except Exception as e:
        logger.exception("Failed to get document structure: %s", e)
        return {"schema": "mimirq.document_structure.v1", "document": {"document_id": document_id}, "nodes": [], "error": str(e)}


async def get_document_structure(
    document_id: str,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Get PageIndex-style section structure derived from existing hierarchy metadata."""
    return await asyncio.to_thread(
        _get_document_structure_sync,
        document_id,
        dataset_id=dataset_id,
        account_id=account_id,
        max_nodes=max_nodes,
    )


def _parse_pages_selector(pages: Any) -> list[int]:
    if pages is None:
        return []
    if isinstance(pages, int):
        return [pages] if pages > 0 else []
    raw = str(pages or "").strip()
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except Exception:
                continue
            if start <= 0 or end <= 0:
                continue
            lo, hi = sorted((start, end))
            out.extend(range(lo, min(hi, lo + 99) + 1))
            continue
        try:
            value = int(token)
        except Exception:
            continue
        if value > 0:
            out.append(value)
    return sorted(set(out))[:100]


def _get_page_content_sync(
    document_id: str,
    pages: Any,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    selected_pages = _parse_pages_selector(pages)
    if not selected_pages:
        result = _get_document_content_sync(
            document_id=document_id,
            page=None,
            dataset_id=dataset_id,
            account_id=account_id,
            max_chars=max_chars,
        )
        result["pages_requested"] = []
        return result

    parts: list[str] = []
    returned_chunks = 0
    truncated = False
    remaining = max(1_000, min(int(max_chars or 50_000), 500_000))
    last: dict[str, Any] = {"document_id": document_id, "dataset_id": dataset_id}
    for page in selected_pages:
        if remaining <= 0:
            truncated = True
            break
        result = _get_document_content_sync(
            document_id=document_id,
            page=page,
            dataset_id=dataset_id,
            account_id=account_id,
            max_chars=remaining,
        )
        last = result
        if result.get("error"):
            return {**result, "pages_requested": selected_pages}
        text = str(result.get("content") or "")
        if text.strip():
            prefix = f"\n\n[page {page}]\n" if parts else f"[page {page}]\n"
            parts.append(prefix + text)
            remaining -= len(prefix) + len(text)
        returned_chunks += int(result.get("returned_chunks") or 0)
        if result.get("truncated"):
            truncated = True
            break

    return {
        "document_id": document_id,
        "dataset_id": dataset_id,
        "filename": last.get("filename"),
        "file_type": last.get("file_type"),
        "pages_requested": selected_pages,
        "pages": selected_pages,
        "returned_chunks": int(returned_chunks),
        "truncated": bool(truncated),
        "content": "".join(parts),
    }


async def get_page_content(
    document_id: str,
    pages: Any,
    *,
    dataset_id: str | None = None,
    account_id: str | None = None,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    """Get page-range content for PageIndex-style tool-agent retrieval."""
    return await asyncio.to_thread(
        _get_page_content_sync,
        document_id,
        pages,
        dataset_id=dataset_id,
        account_id=account_id,
        max_chars=max_chars,
    )


# ============================================================================
# Utility Tools
# ============================================================================


_MAX_MATH_EXPRESSION_CHARS = 256
_MAX_MATH_AST_NODES = 200
_MAX_MATH_INT_BITS = 4096
_MAX_MATH_POW_ABS_EXP = 4096


def _safe_eval_math(expression: str, allowed_names: dict[str, Any]) -> Any:
    expr = (expression or "").strip().lower()
    if not expr:
        raise ValueError("Empty expression")
    if len(expr) > _MAX_MATH_EXPRESSION_CHARS:
        raise ValueError("Expression too long")

    # Keep compatibility: treat "^" as power.
    expr = expr.replace("^", "**")

    tree = ast.parse(expr, mode="eval")

    node_count = 0

    def _bump(_node: ast.AST) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > _MAX_MATH_AST_NODES:
            raise ValueError("Expression too complex")

    def _ensure_number_safe(value: Any) -> None:
        if isinstance(value, bool):
            raise ValueError("Invalid number")
        if isinstance(value, int) and value.bit_length() > _MAX_MATH_INT_BITS:
            raise ValueError(_NUMBER_TOO_LARGE_ERROR)

    def _safe_pow(base: Any, exp: Any, mod: Any | None = None) -> Any:
        if isinstance(base, bool) or isinstance(exp, bool) or isinstance(mod, bool):
            raise ValueError("Invalid number")

        if isinstance(exp, int):
            if abs(exp) > _MAX_MATH_POW_ABS_EXP:
                raise ValueError("Exponent too large")
            if isinstance(base, int) and exp >= 0 and base not in (0, 1, -1):
                estimated_bits = abs(exp) * max(1, base.bit_length())
                if estimated_bits > _MAX_MATH_INT_BITS:
                    raise ValueError(_NUMBER_TOO_LARGE_ERROR)

        if mod is not None:
            if not (isinstance(base, int) and isinstance(exp, int) and isinstance(mod, int)):
                raise ValueError("pow(a, b, mod) only supports integers")
            if mod == 0:
                raise ValueError("Modulo cannot be zero")
            out = pow(base, exp, mod)
            _ensure_number_safe(out)
            return out

        out = base ** exp
        _ensure_number_safe(out)
        return out

    def _eval(node: ast.AST) -> Any:
        _bump(node)

        if isinstance(node, ast.Expression):
            return _eval(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                _ensure_number_safe(node.value)
                return node.value
            raise ValueError("Only numbers are allowed")

        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                out = +operand
            elif isinstance(node.op, ast.USub):
                out = -operand
            else:
                raise ValueError("Unsupported unary operator")
            _ensure_number_safe(out)
            return out

        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)

            if isinstance(node.op, ast.Add):
                out = left + right
            elif isinstance(node.op, ast.Sub):
                out = left - right
            elif isinstance(node.op, ast.Mult):
                if isinstance(left, int) and isinstance(right, int):
                    if left.bit_length() + right.bit_length() > _MAX_MATH_INT_BITS:
                        raise ValueError(_NUMBER_TOO_LARGE_ERROR)
                out = left * right
            elif isinstance(node.op, ast.Div):
                out = left / right
            elif isinstance(node.op, ast.FloorDiv):
                out = left // right
            elif isinstance(node.op, ast.Mod):
                out = left % right
            elif isinstance(node.op, ast.Pow):
                out = _safe_pow(left, right)
            else:
                raise ValueError("Unsupported operator")

            _ensure_number_safe(out)
            return out

        if isinstance(node, ast.Name):
            name = node.id
            if name not in allowed_names:
                raise ValueError(f"Unknown name: {name}")
            value = allowed_names[name]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                _ensure_number_safe(value)
                return value
            raise ValueError(f"'{name}' must be called as a function")

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only direct function calls are allowed")
            if node.keywords:
                raise ValueError("Keyword arguments are not allowed")

            name = node.func.id
            fn = allowed_names.get(name)
            if fn is None or not callable(fn):
                raise ValueError(f"Unknown function: {name}")

            args = [_eval(a) for a in node.args]

            if name == "pow":
                if len(args) not in (2, 3):
                    raise ValueError("pow() expects 2 or 3 arguments")
                return _safe_pow(args[0], args[1], args[2] if len(args) == 3 else None)

            out = fn(*args)
            _ensure_number_safe(out)
            return out

        if isinstance(node, (ast.Tuple, ast.List)):
            return [_eval(elt) for elt in node.elts]

        raise ValueError("Unsupported expression")

    return _eval(tree)


def _resolve_timezone(name: str | None):
    raw = str(name or "").strip()
    if not raw:
        return UTC
    with contextlib.suppress(Exception):
        return ZoneInfo(raw)
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
        return {
            "expression": expression,
            "result": None,
            "success": False,
            "error": str(e),
        }


def format_number(
    number: float,
    decimals: int = 2,
    thousands_separator: bool = True,
) -> dict[str, str]:
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

        return {
            "original": str(number),
            "formatted": formatted,
            "success": True,
        }
    except Exception as e:
        return {
            "original": str(number),
            "formatted": str(number),
            "success": False,
            "error": str(e),
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
            return {
                "value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "success": False,
                "error": str(e),
            }

    if from_unit not in conversions or to_unit not in conversions:
        return {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "success": False,
            "error": "Unknown unit",
        }

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
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "shall",
        "can", "need", "dare", "ought", "used", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between", "under",
        "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "and", "but",
        "if", "or", "because", "until", "while", "although", "though",
        "的", "是", "在", "有", "和", "与", "了", "不", "人", "我",
        "他", "她", "它", "们", "这", "那", "就", "也", "都", "而",
        "及", "着", "或", "把", "被", "让", "给", "到", "从", "向",
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
        description="Search documents in the knowledge base",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query", required=True),
            ToolParameter(name="top_k", type="integer", description="Number of results", default=5),
            ToolParameter(name="dataset_id", type="string", description="Dataset ID (UUID)", required=True),
            ToolParameter(name="filter", type="object", description="Optional metadata filter", default=None),
        ],
    )

    registry.register(
        name="get_document_content",
        func=get_document_content,
        description="Get full content of a document (assembled from chunks)",
        parameters=[
            ToolParameter(name="document_id", type="string", description="Document ID (UUID)", required=True),
            ToolParameter(name="dataset_id", type="string", description="Dataset ID (UUID)", required=True),
            ToolParameter(name="page", type="integer", description="Optional page number", default=None),
            ToolParameter(name="account_id", type="string", description="Optional account/user id for ACL trimming", default=None),
            ToolParameter(name="max_chars", type="integer", description="Max characters to return", default=50000),
        ],
    )

    registry.register(
        name="get_document",
        func=get_document,
        description="Get bounded document metadata",
        parameters=[
            ToolParameter(name="document_id", type="string", description="Document ID (UUID)", required=True),
            ToolParameter(name="dataset_id", type="string", description="Dataset ID (UUID)", required=True),
            ToolParameter(name="account_id", type="string", description="Optional account/user id for ACL trimming", default=None),
        ],
    )

    registry.register(
        name="get_document_structure",
        func=get_document_structure,
        description="Get document section structure from existing hierarchy metadata",
        parameters=[
            ToolParameter(name="document_id", type="string", description="Document ID (UUID)", required=True),
            ToolParameter(name="dataset_id", type="string", description="Dataset ID (UUID)", required=True),
            ToolParameter(name="account_id", type="string", description="Optional account/user id for ACL trimming", default=None),
            ToolParameter(name="max_nodes", type="integer", description="Max structure nodes", default=200),
        ],
    )

    registry.register(
        name="get_page_content",
        func=get_page_content,
        description="Get page or page-range content for document-structure navigation",
        parameters=[
            ToolParameter(name="document_id", type="string", description="Document ID (UUID)", required=True),
            ToolParameter(name="pages", type="string", description="Page selector, e.g. '3', '5-7', or '3,8'", required=True),
            ToolParameter(name="dataset_id", type="string", description="Dataset ID (UUID)", required=True),
            ToolParameter(name="account_id", type="string", description="Optional account/user id for ACL trimming", default=None),
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
