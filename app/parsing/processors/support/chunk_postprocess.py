"""Chunk post-processing helpers: truncation, sampling, offset rebasing, small-chunk merging."""

from typing import Any

from langchain_core.documents import Document

from app.parsing.processors.support.assets import _chunk_has_asset


def _uniform_sample_indices(indices: list[int], k: int) -> list[int]:
    if k <= 0:
        return []
    if k >= len(indices):
        return list(indices)
    if k == 1:
        return [indices[len(indices) // 2]]

    picked, seen = _initial_uniform_sample(indices, k)
    if len(picked) < k:
        _fill_uniform_sample(indices, picked=picked, seen=seen, k=k)
    return picked[:k]


def _initial_uniform_sample(indices: list[int], k: int) -> tuple[list[int], set[int]]:
    n = len(indices)
    picked: list[int] = []
    seen: set[int] = set()
    for i in range(k):
        pos = round(i * (n - 1) / (k - 1))
        pos = max(0, min(n - 1, int(pos)))
        idx = indices[pos]
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(idx)
    return picked, seen


def _fill_uniform_sample(indices: list[int], *, picked: list[int], seen: set[int], k: int) -> None:
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(idx)
        if len(picked) >= k:
            break


def _chunk_asset_indices(chunks: list[Document]) -> list[int]:
    asset_indices: list[int] = []
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
        if _chunk_has_asset(meta):
            asset_indices.append(idx)
    return asset_indices


def _chunk_has_record_identity(chunk: Document) -> bool:
    return _chunk_record_identity_key(chunk) is not None


def _should_skip_near_dedup_for_chunk(chunk: Document) -> bool:
    meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
    return _chunk_has_asset(meta) or _chunk_has_record_identity(chunk)


def _truncate_head_chunks(
    chunks: list[Document],
    *,
    max_chunks: int,
    asset_indices: list[int],
) -> tuple[list[Document], dict[str, Any]]:
    kept_chunks = chunks[:max_chunks]
    asset_kept = sum(
        1 for c in kept_chunks if _chunk_has_asset(c.metadata if isinstance(getattr(c, "metadata", None), dict) else {})
    )
    return kept_chunks, {
        "strategy": "head",
        "asset_total": int(len(asset_indices)),
        "asset_kept": int(asset_kept),
    }


def _truncate_asset_uniform_chunks(
    chunks: list[Document],
    *,
    max_chunks: int,
    asset_indices: list[int],
) -> tuple[list[Document], dict[str, Any]]:
    must_keep = [0]
    for idx in asset_indices:
        if idx not in must_keep:
            must_keep.append(idx)
    if len(must_keep) > max_chunks:
        must_keep = must_keep[:max_chunks]

    keep_set = set(must_keep)
    remaining_slots = max_chunks - len(must_keep)
    if remaining_slots > 0:
        candidate_indices = [i for i in range(len(chunks)) if i not in keep_set]
        keep_set |= set(_uniform_sample_indices(candidate_indices, remaining_slots))

    return [chunks[i] for i in range(len(chunks)) if i in keep_set], {
        "strategy": "asset_uniform",
        "asset_total": int(len(asset_indices)),
        "asset_kept": int(sum(1 for idx in asset_indices if idx in keep_set)),
    }


def _truncate_chunks_for_limit(
    chunks: list[Document],
    *,
    max_chunks: int,
    strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    if max_chunks <= 0 or not chunks or len(chunks) <= max_chunks:
        return chunks, {"strategy": (strategy or "head").strip().lower() or "head", "asset_total": 0, "asset_kept": 0}
    if any(_chunk_has_record_identity(chunk) for chunk in chunks):
        asset_indices = _chunk_asset_indices(chunks)
        return chunks, {
            "strategy": "record_identity_preserved",
            "asset_total": int(len(asset_indices)),
            "asset_kept": int(len(asset_indices)),
            "truncation_skipped": True,
        }

    strategy_norm = (strategy or "head").strip().lower() or "head"
    asset_indices = _chunk_asset_indices(chunks)
    if strategy_norm not in {"head", "asset_uniform"}:
        strategy_norm = "head"
    if strategy_norm == "head":
        return _truncate_head_chunks(chunks, max_chunks=max_chunks, asset_indices=asset_indices)
    return _truncate_asset_uniform_chunks(chunks, max_chunks=max_chunks, asset_indices=asset_indices)


def _ensure_ingest_page_indices(documents: list[Document]) -> None:
    """
    Ensure each parsed Document has a stable per-document index for offset rebasing.

    Why:
    - Many parsers (e.g. PDF) emit multiple Documents.
    - Most chunkers compute start/end offsets relative to each `doc.page_content`.
    - We persist parsed markdown by joining docs; to highlight chunks reliably,
      we need global offsets (joined-text coordinates).
    """
    for i, doc in enumerate(documents or []):
        meta = dict(getattr(doc, "metadata", None) or {})
        meta.setdefault("page_index", i + 1)  # 1-based (align with chunk-preview)
        doc.metadata = meta


def _joined_text_total_characters(
    documents: list[Document],
    *,
    join_separator: str = "\n\n",
) -> int:
    """Return the joined-text length used for persisted parsed content offsets."""
    if not documents:
        return 0
    sep_len = len(join_separator or "")
    total = 0
    last_index = len(documents) - 1
    for idx, doc in enumerate(documents):
        total += len(doc.page_content or "")
        if idx < last_index:
            total += sep_len
    return int(total)


def _document_page_index(doc: Document, index: int) -> int:
    meta = dict(getattr(doc, "metadata", None) or {})
    try:
        return int(meta.get("page_index") or (index + 1))
    except (TypeError, ValueError, AttributeError):
        return index + 1


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def _chunk_page_index(chunk: Document) -> int | None:
    meta = getattr(chunk, "metadata", None) or {}
    return _optional_int(meta.get("page_index"))


def _build_page_start_offsets(
    documents: list[Document],
    *,
    join_separator: str,
) -> dict[int, int]:
    sep_len = len(join_separator or "")
    page_start: dict[int, int] = {}
    cursor = 0
    last_index = len(documents) - 1
    for index, doc in enumerate(documents):
        # A few parsers can emit multiple Documents for one physical page.  A
        # chunk only carries the page index, so the first document is the only
        # deterministic base we can preserve; later duplicates must not move
        # every chunk on that page to the final fragment's offset.
        page_start.setdefault(_document_page_index(doc, index), cursor)
        cursor += len(doc.page_content or "")
        if index < last_index:
            cursor += sep_len
    return page_start


def _rebase_single_chunk_offsets(chunk: Document, *, page_start: dict[int, int]) -> Document:
    meta = dict(getattr(chunk, "metadata", None) or {})
    page_index = _optional_int(meta.get("page_index"))
    base = page_start.get(page_index, 0) if page_index is not None else 0
    start_i = _optional_int(meta.get("start_char"))
    end_i = _optional_int(meta.get("end_char"))

    if start_i is not None:
        meta.setdefault("start_char_local", start_i)
        meta["start_char"] = base + start_i
    if end_i is not None:
        meta.setdefault("end_char_local", end_i)
        meta["end_char"] = base + end_i
    if page_index is not None:
        meta.setdefault("start_char_base", base)

    meta.setdefault("offsets_rebased", True)
    return Document(page_content=chunk.page_content, metadata=meta, id=getattr(chunk, "id", None))


def _rebase_chunk_offsets_by_page_index(
    *,
    documents: list[Document],
    chunks: list[Document],
    join_separator: str = "\n\n",
) -> list[Document]:
    """
    Convert chunk start/end offsets from per-Document coordinates to joined-text coordinates.

    - Assumes chunk metadata contains `page_index` and local `start_char`/`end_char`.
    - Uses the same join separator as persisted parsed content ("\\n\\n").
    """
    if not documents or not chunks:
        return chunks

    page_start = _build_page_start_offsets(documents, join_separator=join_separator)
    return [_rebase_single_chunk_offsets(chunk, page_start=page_start) for chunk in chunks]


def _build_page_text_lookup(
    documents: list[Document],
    *,
    join_separator: str,
) -> tuple[dict[int, str], dict[int, int]]:
    sep_len = len(join_separator or "")
    page_text: dict[int, str] = {}
    page_base: dict[int, int] = {}
    cursor = 0
    last_index = len(documents) - 1
    for index, doc in enumerate(documents):
        page_index = _document_page_index(doc, index)
        page_text.setdefault(page_index, doc.page_content or "")
        page_base.setdefault(page_index, cursor)
        cursor += len(doc.page_content or "")
        if index < last_index:
            cursor += sep_len
    return page_text, page_base


def _chunk_mergeable(chunk: Document) -> bool:
    meta = getattr(chunk, "metadata", None) or {}
    if _chunk_has_asset(meta):
        return False
    return not (meta.get("chunk_role") or meta.get("parent_id"))


def _chunk_record_identity_key(chunk: Document) -> str | None:
    meta = getattr(chunk, "metadata", None) or {}
    record_identity = meta.get("_record_identity") if isinstance(meta, dict) else None
    if not isinstance(record_identity, dict):
        return None
    key = str(record_identity.get("key") or "").strip()
    return key or None


def _chunks_share_record_identity_boundary(first: Document, second: Document) -> bool:
    first_key = _chunk_record_identity_key(first)
    second_key = _chunk_record_identity_key(second)
    if first_key or second_key:
        return bool(first_key and second_key and first_key == second_key)
    return True


def _local_chunk_range(meta: dict[str, Any], *, base: int) -> tuple[int, int] | None:
    # Prefer explicitly stored locals (set by offset rebase stage).
    start_local = meta.get("start_char_local")
    end_local = meta.get("end_char_local")
    start_i = _optional_int(start_local)
    end_i = _optional_int(end_local)

    if start_i is None or end_i is None:
        sg = _optional_int(meta.get("start_char"))
        eg = _optional_int(meta.get("end_char"))
        if sg is None or eg is None:
            return None
        start_i = max(0, sg - base)
        end_i = max(start_i, eg - base)

    if end_i < start_i:
        return None
    return start_i, end_i


_MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS = (
    "content_hash",
    "content_hash_algo",
    "content_len",
    "simhash64",
    "simhash_algo",
    "chunk_quality",
    "chunk_semantic_role",
    "chunk_type",
    "structure",
)


def _retrieval_text_for_merge(chunk: Document, meta: dict[str, Any]) -> str:
    retrieval_text = meta.get("_retrieval_text")
    if isinstance(retrieval_text, str) and retrieval_text.strip():
        return retrieval_text.strip()
    return str(chunk.page_content or "").strip()


def _refresh_merged_chunk_content_metadata(
    meta: dict[str, Any],
    *,
    first: Document,
    second: Document,
    first_meta: dict[str, Any],
    second_meta: dict[str, Any],
    merged_content: str,
) -> None:
    for key in _MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS:
        meta.pop(key, None)

    first_has_retrieval = isinstance(first_meta.get("_retrieval_text"), str) and bool(
        str(first_meta["_retrieval_text"]).strip()
    )
    second_has_retrieval = isinstance(second_meta.get("_retrieval_text"), str) and bool(
        str(second_meta["_retrieval_text"]).strip()
    )
    if first_has_retrieval or second_has_retrieval:
        pieces = [
            text
            for text in (
                _retrieval_text_for_merge(first, first_meta),
                _retrieval_text_for_merge(second, second_meta),
            )
            if text
        ]
        meta["_retrieval_text"] = "\n\n".join(pieces)
        meta["_retrieval_display_content"] = str(merged_content or "")
    else:
        meta.pop("_retrieval_text", None)
        meta.pop("_retrieval_display_content", None)


def _merge_two_small_chunks(
    first: Document,
    second: Document,
    *,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> Document | None:
    text = page_text.get(page_index)
    base = int(page_base.get(page_index) or 0)
    if text is None:
        return None
    if not _chunks_share_record_identity_boundary(first, second):
        return None

    first_meta = dict(getattr(first, "metadata", None) or {})
    second_meta = dict(getattr(second, "metadata", None) or {})
    first_range = _local_chunk_range(first_meta, base=base)
    second_range = _local_chunk_range(second_meta, base=base)
    if first_range is None or second_range is None:
        return None

    start_local = max(0, min(min(first_range[0], second_range[0]), len(text)))
    end_local = max(start_local, min(max(first_range[1], second_range[1]), len(text)))
    first_meta["page_index"] = page_index
    first_meta.setdefault("start_char_base", base)
    first_meta["start_char_local"] = start_local
    first_meta["end_char_local"] = end_local
    first_meta["start_char"] = base + start_local
    first_meta["end_char"] = base + end_local
    first_meta["offsets_rebased"] = True
    first_meta["merged_small_chunks"] = int(first_meta.get("merged_small_chunks") or 0) + 1
    merged_content = text[start_local:end_local]
    _refresh_merged_chunk_content_metadata(
        first_meta,
        first=first,
        second=second,
        first_meta=first_meta,
        second_meta=second_meta,
        merged_content=merged_content,
    )

    return Document(page_content=merged_content, metadata=first_meta, id=getattr(first, "id", None))


def _merge_with_pending_small_chunk(
    *,
    out: list[Document],
    pending: Document,
    current: Document,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> None:
    merged = _merge_two_small_chunks(
        pending,
        current,
        page_index=page_index,
        page_text=page_text,
        page_base=page_base,
    )
    if merged is not None:
        out.append(merged)
        return
    out.append(pending)
    out.append(current)


def _flush_pending_on_page_change(
    *,
    out: list[Document],
    pending: Document | None,
    pending_page: int | None,
    page_index: int | None,
) -> tuple[Document | None, int | None]:
    if pending is not None and page_index != pending_page:
        out.append(pending)
        return None, None
    return pending, pending_page


def _append_unmergeable_chunk(
    *,
    out: list[Document],
    chunk: Document,
    pending: Document | None,
) -> tuple[Document | None, int | None]:
    if pending is not None:
        out.append(pending)
    out.append(chunk)
    return None, None


def _try_merge_with_previous_chunk(
    *,
    out: list[Document],
    chunk: Document,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> bool:
    if not out:
        return False
    prev = out[-1]
    if _chunk_page_index(prev) != page_index or not _chunk_mergeable(prev):
        return False
    merged = _merge_two_small_chunks(
        prev,
        chunk,
        page_index=page_index,
        page_text=page_text,
        page_base=page_base,
    )
    if merged is None:
        return False
    out[-1] = merged
    return True


def _merge_small_chunks_by_min_chars(
    *,
    documents: list[Document],
    chunks: list[Document],
    min_chars: int,
    join_separator: str = "\n\n",
) -> list[Document]:
    """
    Merge very short text chunks with neighbors to reduce over-fragmentation.

    Design goals:
    - Keep merge bounded within the same `page_index` (stable highlighting).
    - Preserve assets (image/table) and parent/child semantics by skipping those chunks.
    - Use original per-page text slice when offsets are available (so content matches offsets).
    """
    min_chars = max(0, int(min_chars or 0))
    if min_chars <= 0 or not documents or not chunks:
        return chunks

    page_text, page_base = _build_page_text_lookup(documents, join_separator=join_separator)

    out: list[Document] = []
    pending: Document | None = None
    pending_page: int | None = None

    for c in chunks:
        page_index = _chunk_page_index(c)
        pending, pending_page = _flush_pending_on_page_change(
            out=out,
            pending=pending,
            pending_page=pending_page,
            page_index=page_index,
        )

        mergeable = page_index is not None and page_index in page_text and _chunk_mergeable(c)
        content_len = len((c.page_content or "").strip())

        if not mergeable:
            pending, pending_page = _append_unmergeable_chunk(out=out, chunk=c, pending=pending)
            continue

        if pending is not None:
            _merge_with_pending_small_chunk(
                out=out,
                pending=pending,
                current=c,
                page_index=page_index,
                page_text=page_text,
                page_base=page_base,
            )
            pending = None
            pending_page = None
            continue

        if content_len >= min_chars:
            out.append(c)
            continue

        # Small chunk: merge into previous if possible, otherwise buffer and merge into next.
        if _try_merge_with_previous_chunk(
            out=out,
            chunk=c,
            page_index=page_index,
            page_text=page_text,
            page_base=page_base,
        ):
            continue

        pending = c
        pending_page = page_index

    if pending is not None:
        out.append(pending)

    return out
