
from typing import Any, Callable, Mapping


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
    normalized = results

    if normalized and document_ids:
        allowed_document_ids = {str(document_id) for document_id in document_ids if document_id is not None}
        if allowed_document_ids:
            filtered_results: list[dict[str, Any]] = []
            for result in normalized:
                metadata = result.get("metadata") or {}
                document_id = metadata.get("document_id") or result.get("document_id")
                if document_id is None:
                    continue
                if str(document_id) in allowed_document_ids:
                    filtered_results.append(result)
            normalized = filtered_results

    if not normalized:
        return normalized

    vector_client_filter = dict(vector_filter or {})
    if runtime_shards_present:
        vector_client_filter.pop("embedding_space_hash", None)
    if vector_client_filter:
        normalized = [
            result
            for result in normalized
            if match_metadata_filter((result.get("metadata") or {}), vector_client_filter)
        ]

    if not normalized:
        return normalized

    lookup = chunk_id_lookup or {}
    for result in normalized:
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

    return normalized
