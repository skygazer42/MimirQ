
from typing import Any


def select_document_expansion_mode(*, total_chunks: int, short_doc_max_chunks: int) -> str:
    try:
        total = int(total_chunks or 0)
    except Exception:
        total = 0
    try:
        threshold = int(short_doc_max_chunks or 0)
    except Exception:
        threshold = 0
    if threshold > 0 and 0 < total <= threshold:
        return "sibling"
    return "neighbor"


def _result_chunk_id(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    return str(result.get("chunk_id") or metadata.get("chunk_id") or "").strip()


def _original_results_map(
    results: list[dict[str, Any]],
    supplied: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    original_map = dict(supplied or {})
    if original_map:
        return original_map
    for item in results or []:
        if not isinstance(item, dict):
            continue
        chunk_id = _result_chunk_id(item)
        if chunk_id:
            original_map[chunk_id] = item
    return original_map


def _row_header_path(row: Any) -> tuple[dict[str, Any], str | None]:
    stored_meta = dict(getattr(row, "doc_metadata", None) or {})
    header_path = str(stored_meta.get("header_path") or stored_meta.get("header_context") or "").strip()
    return stored_meta, header_path or None


def _sibling_metadata(
    *,
    row: Any,
    chunk_id: str,
    stored_meta: dict[str, Any],
    anchor_chunk_id: str,
) -> dict[str, Any]:
    stored_meta.setdefault("tenant_id", str(getattr(row, "tenant_id", "") or ""))
    stored_meta.setdefault("document_id", str(getattr(row, "document_id", "") or ""))
    stored_meta.setdefault("chunk_index", int(getattr(row, "chunk_index", 0) or 0))
    stored_meta.setdefault("chunk_id", chunk_id)
    if getattr(row, "page_number", None) is not None:
        stored_meta.setdefault("page", row.page_number)
    if getattr(row, "start_char", None) is not None:
        stored_meta.setdefault("start_char", row.start_char)
    if getattr(row, "end_char", None) is not None:
        stored_meta.setdefault("end_char", row.end_char)
    stored_meta["sibling_of"] = anchor_chunk_id or None
    stored_meta["retrieval_role"] = "sibling"
    return stored_meta


def _sibling_result(
    *,
    row: Any,
    chunk_id: str,
    stored_meta: dict[str, Any],
    anchor_chunk_id: str,
    anchor_score: float,
) -> dict[str, Any]:
    metadata = _sibling_metadata(
        row=row,
        chunk_id=chunk_id,
        stored_meta=stored_meta,
        anchor_chunk_id=anchor_chunk_id,
    )
    return {
        "chunk_id": chunk_id,
        "content": str(getattr(row, "content", "") or ""),
        "metadata": metadata,
        "score": float(anchor_score * 0.8) if anchor_score else 0.0,
    }


def _append_document_siblings(
    *,
    out: list[dict[str, Any]],
    seen: set[str],
    rows: list[Any],
    original_map: dict[str, dict[str, Any]],
    anchor_chunk_id: str,
    anchor_header_path: str | None,
    anchor_score: float,
    max_added: int,
    added: int,
) -> int:
    ordered_rows = sorted(rows, key=lambda item: int(getattr(item, "chunk_index", 0) or 0))
    for row in ordered_rows:
        chunk_id = str(getattr(row, "id", "") or "").strip()
        if not chunk_id or chunk_id in seen:
            continue
        stored_meta, row_header_path = _row_header_path(row)
        if anchor_header_path and row_header_path and row_header_path != anchor_header_path:
            continue
        original = original_map.get(chunk_id)
        if isinstance(original, dict):
            out.append(original)
            seen.add(chunk_id)
            continue
        if max_added and added >= max_added:
            continue
        out.append(
            _sibling_result(
                row=row,
                chunk_id=chunk_id,
                stored_meta=stored_meta,
                anchor_chunk_id=anchor_chunk_id,
                anchor_score=anchor_score,
            )
        )
        seen.add(chunk_id)
        added += 1
    return added


def expand_document_siblings(
    *,
    results: list[dict[str, Any]],
    document_chunks_by_doc: dict[str, list[Any]],
    short_doc_ids: set[str],
    max_added: int = 0,
    original_results_by_chunk_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    original_map = _original_results_map(results, original_results_by_chunk_id)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    expanded_docs: set[str] = set()
    added = 0

    for result in results or []:
        if not isinstance(result, dict):
            continue
        meta = result.get("metadata") or {}
        doc_key = str(meta.get("document_id") or "").strip()
        anchor_cid = _result_chunk_id(result)
        anchor_header_path = str(meta.get("header_path") or meta.get("header_context") or "").strip() or None
        anchor_score = float(result.get("score") or 0.0) if result.get("score") is not None else 0.0

        if not doc_key or doc_key not in short_doc_ids:
            if anchor_cid and anchor_cid not in seen:
                out.append(result)
                seen.add(anchor_cid)
            continue
        if doc_key in expanded_docs:
            continue
        added = _append_document_siblings(
            out=out,
            seen=seen,
            rows=document_chunks_by_doc.get(doc_key) or [],
            original_map=original_map,
            anchor_chunk_id=anchor_cid,
            anchor_header_path=anchor_header_path,
            anchor_score=anchor_score,
            max_added=max_added,
            added=added,
        )
        expanded_docs.add(doc_key)

    return out


__all__ = ["expand_document_siblings", "select_document_expansion_mode"]
