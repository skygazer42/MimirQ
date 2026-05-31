from __future__ import annotations

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


def expand_document_siblings(
    *,
    results: list[dict[str, Any]],
    document_chunks_by_doc: dict[str, list[Any]],
    short_doc_ids: set[str],
    max_added: int = 0,
    original_results_by_chunk_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    original_map = dict(original_results_by_chunk_id or {})
    if not original_map:
        for item in results or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chunk_id") or ((item.get("metadata") or {}).get("chunk_id")) or "").strip()
            if cid:
                original_map[cid] = item
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    expanded_docs: set[str] = set()
    added = 0

    for result in results or []:
        if not isinstance(result, dict):
            continue
        meta = result.get("metadata") or {}
        doc_key = str(meta.get("document_id") or "").strip()
        anchor_cid = str(result.get("chunk_id") or meta.get("chunk_id") or "").strip()
        anchor_header_path = str(meta.get("header_path") or meta.get("header_context") or "").strip() or None
        anchor_score = float(result.get("score") or 0.0) if result.get("score") is not None else 0.0

        if doc_key and doc_key in short_doc_ids:
            if doc_key in expanded_docs:
                continue
            rows = sorted(
                document_chunks_by_doc.get(doc_key) or [],
                key=lambda item: int(getattr(item, "chunk_index", 0) or 0),
            )
            for row in rows:
                cid = str(getattr(row, "id", "") or "").strip()
                if not cid or cid in seen:
                    continue

                stored_meta = dict(getattr(row, "doc_metadata", None) or {})
                row_header_path = str(
                    stored_meta.get("header_path") or stored_meta.get("header_context") or ""
                ).strip() or None
                if anchor_header_path and row_header_path and row_header_path != anchor_header_path:
                    continue

                original = original_map.get(cid)
                if isinstance(original, dict):
                    out.append(original)
                    seen.add(cid)
                    continue

                if max_added and added >= max_added:
                    continue

                stored_meta.setdefault("tenant_id", str(getattr(row, "tenant_id", "") or ""))
                stored_meta.setdefault("document_id", str(getattr(row, "document_id", "") or ""))
                stored_meta.setdefault("chunk_index", int(getattr(row, "chunk_index", 0) or 0))
                stored_meta.setdefault("chunk_id", cid)
                if getattr(row, "page_number", None) is not None:
                    stored_meta.setdefault("page", row.page_number)
                if getattr(row, "start_char", None) is not None:
                    stored_meta.setdefault("start_char", row.start_char)
                if getattr(row, "end_char", None) is not None:
                    stored_meta.setdefault("end_char", row.end_char)
                stored_meta["sibling_of"] = anchor_cid or None
                stored_meta["retrieval_role"] = "sibling"

                out.append(
                    {
                        "chunk_id": cid,
                        "content": str(getattr(row, "content", "") or ""),
                        "metadata": stored_meta,
                        "score": float(anchor_score * 0.8) if anchor_score else 0.0,
                    }
                )
                seen.add(cid)
                added += 1
            expanded_docs.add(doc_key)
            continue

        if anchor_cid and anchor_cid not in seen:
            out.append(result)
            seen.add(anchor_cid)

    return out


__all__ = ["expand_document_siblings", "select_document_expansion_mode"]
