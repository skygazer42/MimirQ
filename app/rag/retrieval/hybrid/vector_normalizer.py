
from typing import Any, Callable, Mapping


def _filter_vector_results_by_document_ids(
    results: list[dict[str, Any]],
    *,
    document_ids: list[Any] | None,
) -> list[dict[str, Any]]:
    if not results or not document_ids:
        return results

    allowed_document_ids = {str(document_id) for document_id in document_ids if document_id is not None}
    if not allowed_document_ids:
        return results

    filtered_results: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata") or {}
        document_id = metadata.get("document_id") or result.get("document_id")
        if document_id is None:
            continue
        if str(document_id) in allowed_document_ids:
            filtered_results.append(result)
    return filtered_results


def _apply_vector_client_filter(
    results: list[dict[str, Any]],
    *,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    vector_client_filter = dict(vector_filter or {})
    if runtime_shards_present:
        vector_client_filter.pop("embedding_space_hash", None)
    if not vector_client_filter:
        return results
    return [
        result
        for result in results
        if match_metadata_filter((result.get("metadata") or {}), vector_client_filter)
    ]


def _backfill_chunk_ids(
    results: list[dict[str, Any]],
    *,
    chunk_id_lookup: Mapping[str, str] | None,
) -> None:
    lookup = chunk_id_lookup or {}
    for result in results:
        metadata = result.get("metadata") or {}
        existing_chunk_id = result.get("chunk_id") or metadata.get("chunk_id")
        if existing_chunk_id:
            chunk_id = str(existing_chunk_id)
            result["chunk_id"] = chunk_id
            metadata = dict(metadata)
            metadata["chunk_id"] = chunk_id
            result["metadata"] = metadata
            continue

        document_id = metadata.get("document_id")
        chunk_index = metadata.get("chunk_index")
        if document_id is None or chunk_index is None:
            continue

        chunk_id = None
        document_pipeline_key = metadata.get("doc_pipeline_key")
        if document_pipeline_key is not None:
            chunk_id = lookup.get(f"{document_pipeline_key}:{chunk_index}")
        if not chunk_id:
            chunk_id = lookup.get(f"{document_id}:{chunk_index}")
        if not chunk_id:
            continue

        result["chunk_id"] = chunk_id
        metadata["chunk_id"] = chunk_id
        result["metadata"] = metadata


def normalize_vector_channel_results(
    results: list[dict[str, Any]],
    *,
    document_ids: list[Any] | None,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    chunk_id_lookup: Mapping[str, str] | None,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Apply client-side vector scope checks and chunk-id backfill."""
    normalized = _filter_vector_results_by_document_ids(results, document_ids=document_ids)

    if not normalized:
        return normalized

    normalized = _apply_vector_client_filter(
        normalized,
        vector_filter=vector_filter,
        runtime_shards_present=runtime_shards_present,
        match_metadata_filter=match_metadata_filter,
    )

    if not normalized:
        return normalized

    _backfill_chunk_ids(normalized, chunk_id_lookup=chunk_id_lookup)

    return normalized
