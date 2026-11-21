from typing import Any

from app.types.document_metadata import metadata_text


def select_document_expansion_mode(*, total_chunks: int, short_doc_max_chunks: int) -> str:
    if short_doc_max_chunks > 0 and 0 < total_chunks <= short_doc_max_chunks:
        return "sibling"
    return "neighbor"


def result_chunk_id(result: dict[str, Any]) -> str:
    return str(result["chunk_id"]).strip()


def build_original_result_map(
    results: list[dict[str, Any]],
    supplied: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    original_map = dict((supplied if supplied is not None else {}))
    if original_map:
        return original_map
    for item in results:
        chunk_id = result_chunk_id(item)
        if chunk_id:
            original_map[chunk_id] = item
    return original_map


def metadata_header_path(metadata: dict[str, Any]) -> str | None:
    header_path = metadata_text(metadata, "header_path") or metadata_text(metadata, "header_context")
    return header_path if header_path else None


def _row_header_path(row: Any) -> tuple[dict[str, Any], str | None]:
    stored_meta = dict(row.doc_metadata or {})
    return stored_meta, metadata_header_path(stored_meta)


def _sibling_metadata(
    *,
    row: Any,
    chunk_id: str,
    stored_meta: dict[str, Any],
    anchor_chunk_id: str,
) -> dict[str, Any]:
    stored_meta.setdefault("tenant_id", str(row.tenant_id))
    stored_meta.setdefault("document_id", str(row.document_id))
    stored_meta.setdefault("chunk_index", row.chunk_index)
    stored_meta.setdefault("chunk_id", chunk_id)
    if row.page_number is not None:
        stored_meta.setdefault("page", row.page_number)
    if row.start_char is not None:
        stored_meta.setdefault("start_char", row.start_char)
    if row.end_char is not None:
        stored_meta.setdefault("end_char", row.end_char)
    stored_meta["sibling_of"] = anchor_chunk_id
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
        "content": row.content,
        "metadata": metadata,
        "score": anchor_score * 0.8 if anchor_score else 0.0,
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
    ordered_rows = sorted(rows, key=lambda item: item.chunk_index)
    for row in ordered_rows:
        chunk_id = str(row.id).strip()
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
    original_map = build_original_result_map(results, original_results_by_chunk_id)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    expanded_docs: set[str] = set()
    added = 0

    for result in results:
        meta = result.get("metadata") or {}
        doc_key = metadata_text(meta, "document_id")
        anchor_cid = result_chunk_id(result)
        anchor_header_path = metadata_header_path(meta)
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


__all__ = [
    "build_original_result_map",
    "expand_document_siblings",
    "metadata_header_path",
    "result_chunk_id",
    "select_document_expansion_mode",
]
