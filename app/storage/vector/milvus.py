"""
Milvus vector store service

Provides two usage modes:
1. Singleton mode - Used for document vector storage (fixed collection)
2. Multi-instance mode - Used for KG entities/events (customizable collection)
"""

import re
import threading
from typing import Any, Optional
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders, MilvusConfig
from app.rag.core.filters import match_metadata_filter as _match_metadata_filter
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.contracts import INDEXED_METADATA_KEY

logger = get_logger("storage.vector.milvus")

_MILVUS_MAX_VARCHAR_BYTES = 65_535
_MILVUS_EXPR_MAX_CHARS = 8000
_MILVUS_EXPR_AND = " and "
_MILVUS_EXPR_OR = " or "
_MILVUS_FALLBACK_LOG_MESSAGE = "Ignoring non-critical Milvus fallback failure: %s"
_MILVUS_FIELD_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
_MILVUS_WARNED_WRITE_COMPAT_FALLBACK = False
_MILVUS_WARNED_SEARCH_EXPR_FALLBACK = False
_INDEXED_METADATA_VIEW_KEY = INDEXED_METADATA_KEY
_INDEXED_METADATA_FILTERS_KEY = "__indexed_metadata_filters__"
_INDEXED_METADATA_SLOT_COUNT = 16
_INDEXED_METADATA_SLOT_FIELD_PAIRS = tuple(
    (f"indexed_meta_{idx:02d}_key", f"indexed_meta_{idx:02d}_value")
    for idx in range(1, _INDEXED_METADATA_SLOT_COUNT + 1)
)
_INDEXED_METADATA_VALUE_EXPR_FIELD = _INDEXED_METADATA_SLOT_FIELD_PAIRS[0][1]
_INDEXED_METADATA_SLOT_FIELDS = frozenset(
    field for pair in _INDEXED_METADATA_SLOT_FIELD_PAIRS for field in pair
)

# Safe allowlist for metadata expr pushdown (must exist in collection schema).
_MILVUS_NUMERIC_FIELDS = frozenset({"chunk_index", "page_number"})
_MILVUS_STRING_FIELDS = frozenset(
    {
        "tenant_id",
        "dataset_id",
        "document_id",
        "embedding_space_hash",
        "chunk_id",
        # Versioning / rollback (stable composite key).
        "pipeline_hash",
        "doc_pipeline_key",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
        # KG (optional; depends on collection schema)
        "index_kind",
        "type",
        "name",
        "title",
    }
    | _INDEXED_METADATA_SLOT_FIELDS
)
_MILVUS_ALLOWED_FILTER_FIELDS = _MILVUS_NUMERIC_FIELDS | _MILVUS_STRING_FIELDS

# Document collection (knowledge base chunks) stores a fixed subset of metadata fields.
# Keep this list in sync with MilvusVectorStore.add_documents().
_DOC_VECTOR_METADATA_FIELDS = frozenset(
    {
        "tenant_id",
        "dataset_id",
        "document_id",
        "embedding_space_hash",
        "chunk_index",
        "chunk_id",
        "pipeline_hash",
        "doc_pipeline_key",
        "page_number",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
    }
    | _INDEXED_METADATA_SLOT_FIELDS
)

# Public-facing aliases commonly used in the retrieval layer.
_MILVUS_FILTER_KEY_ALIASES: dict[str, str] = {
    "page": "page_number",
    "img_url": "image_url",
}


def _ensure_milvus_collection_loaded(store: Any) -> bool:
    """Ensure a LangChain Milvus store has a loaded collection before delete ops."""
    from pymilvus import Collection

    if isinstance(getattr(store, "col", None), Collection):
        return True

    init_kwargs: dict[str, Any] = {}
    partition_names = getattr(store, "partition_names", None)
    if partition_names:
        init_kwargs["partition_names"] = partition_names
    replica_number = getattr(store, "replica_number", None)
    if replica_number:
        init_kwargs["replica_number"] = replica_number
    store_timeout = getattr(store, "timeout", None)
    if store_timeout:
        init_kwargs["timeout"] = store_timeout

    store._init(**init_kwargs)  # type: ignore[attr-defined]
    return isinstance(getattr(store, "col", None), Collection)


def _normalize_indexed_metadata_filter_key(raw_key: str) -> str | None:
    key = str(raw_key or "").strip()
    if not key:
        return None
    prefix = f"{_INDEXED_METADATA_VIEW_KEY}."
    if key.startswith(prefix):
        field = key[len(prefix) :].strip()
        return field or None
    if key.startswith("$") or key.startswith("_") or "." in key:
        return None
    return key


def _stringify_indexed_metadata_value(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return text[:_MILVUS_MAX_VARCHAR_BYTES]


def _iter_indexed_metadata_slot_items(meta: dict[str, Any]) -> list[tuple[str, str]]:
    indexed = meta.get(_INDEXED_METADATA_VIEW_KEY)
    if not isinstance(indexed, dict):
        return []

    items: list[tuple[str, str]] = []
    for raw_key, raw_value in sorted(indexed.items(), key=lambda item: str(item[0])):
        key = str(raw_key or "").strip()
        if not key:
            continue
        values = raw_value if isinstance(raw_value, (list, tuple, set)) else [raw_value]
        for value in values:
            if value in (None, "", [], {}):
                continue
            normalized_value = _stringify_indexed_metadata_value(value)
            if not normalized_value:
                continue
            items.append((key[:512], normalized_value))
            if len(items) >= _INDEXED_METADATA_SLOT_COUNT:
                return items
    return items


def _flatten_indexed_metadata_slots(meta: dict[str, Any]) -> dict[str, str]:
    slots = {
        field_name: ""
        for key_field, value_field in _INDEXED_METADATA_SLOT_FIELD_PAIRS
        for field_name in (key_field, value_field)
    }
    for (key_field, value_field), (key, value) in zip(
        _INDEXED_METADATA_SLOT_FIELD_PAIRS,
        _iter_indexed_metadata_slot_items(meta),
        strict=False,
    ):
        slots[key_field] = key
        slots[value_field] = value
    return slots


def _rehydrate_indexed_metadata_slots(meta: dict[str, Any]) -> dict[str, Any]:
    out = dict(meta or {})
    if isinstance(out.get(_INDEXED_METADATA_VIEW_KEY), dict):
        return out

    indexed: dict[str, Any] = {}
    for key_field, value_field in _INDEXED_METADATA_SLOT_FIELD_PAIRS:
        key = str(out.get(key_field) or "").strip()
        value = str(out.get(value_field) or "").strip()
        if not key or not value:
            continue
        existing = indexed.get(key)
        if existing is None:
            indexed[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            indexed[key] = [existing, value]
    if indexed:
        out[_INDEXED_METADATA_VIEW_KEY] = indexed
    return out


def _milvus_client_filter_spec(supported_filter: dict[str, Any]) -> dict[str, Any]:
    out = {
        key: value
        for key, value in (supported_filter or {}).items()
        if key != _INDEXED_METADATA_FILTERS_KEY
    }
    for item in supported_filter.get(_INDEXED_METADATA_FILTERS_KEY, []) or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        out[field] = item.get("condition")
    return out


def _milvus_scalar_client_filter_spec(supported_filter: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in (supported_filter or {}).items()
        if key != _INDEXED_METADATA_FILTERS_KEY
    }


def _sanitize_milvus_metadata_filter(
    metadata_filter: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Return a safe, best-effort filter spec that only contains supported keys.

    Notes:
    - Dotted (nested) keys are not supported in Milvus scalar expr and are dropped.
    - This is intentionally conservative: it prevents "missing-field" false negatives when
      callers include rich metadata filters that are only available in Postgres.
    """
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return {}

    allowed = allowed_fields or set(_MILVUS_ALLOWED_FILTER_FIELDS)
    cleaned: dict[str, Any] = {}
    for raw_key, condition in metadata_filter.items():
        if not isinstance(raw_key, str):
            continue
        indexed_field = _normalize_indexed_metadata_filter_key(raw_key)
        if indexed_field and indexed_field not in allowed:
            cleaned.setdefault(_INDEXED_METADATA_FILTERS_KEY, []).append(
                {"field": indexed_field, "condition": condition}
            )
            continue
        if "." in raw_key:
            continue
        key = _MILVUS_FILTER_KEY_ALIASES.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if not _MILVUS_FIELD_NAME_RE.match(key):
            continue
        cleaned[key] = condition
    return cleaned


def _coerce_milvus_metadata_value(value: Any) -> Any:
    """Milvus does not support None values for scalar fields."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value[:_MILVUS_MAX_VARCHAR_BYTES]
    return str(value)[:_MILVUS_MAX_VARCHAR_BYTES]


def _normalize_milvus_metadata_batch(metadatas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure consistent keys and Milvus-compatible values across a batch."""
    if not metadatas:
        return []

    schema_meta: dict[str, Any] = {}
    for k, v in (metadatas[0] or {}).items():
        schema_meta[str(k)] = _coerce_milvus_metadata_value(v)

    schema_keys = list(schema_meta.keys())
    normalized: list[dict[str, Any]] = []
    for meta in metadatas:
        normalized_meta = dict(meta or {})
        # Normalize values for known keys first.
        for k in list(normalized_meta.keys()):
            normalized_meta[k] = _coerce_milvus_metadata_value(normalized_meta.get(k))

        # Fill missing schema keys so insert columns remain aligned.
        for k in schema_keys:
            if k in normalized_meta and normalized_meta[k] != "":
                continue
            exemplar = schema_meta.get(k)
            if isinstance(exemplar, bool):
                normalized_meta[k] = False
            elif isinstance(exemplar, int):
                normalized_meta[k] = 0
            elif isinstance(exemplar, float):
                normalized_meta[k] = 0.0
            else:
                normalized_meta[k] = ""
        normalized.append(normalized_meta)

    return normalized


def _escape_milvus_string(value: str) -> str:
    # Milvus expr strings use double quotes; escape minimal set.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _chunk_in_list_values(
    values: list[str],
    *,
    field: str,
    max_expr_chars: int,
    max_items: int,
) -> list[list[str]]:
    """
    Chunk a list of string values for a Milvus `field in ["..."]` expression.

    Constraints:
    - limit by item count (max_items)
    - limit by expr length (max_expr_chars) (best-effort; avoid server-side rejects)
    """
    safe_field = str(field or "").strip() or "id"
    cap_chars = max(256, int(max_expr_chars or 0))
    cap_items = max(1, int(max_items or 0))

    # Overhead: `field in [` + `]`
    overhead = len(safe_field) + len(' in [""]')

    batches: list[list[str]] = []
    cur: list[str] = []
    cur_len = overhead
    for raw in values or []:
        v = str(raw)
        # Each value contributes: quotes + escaped content + comma+space.
        escaped = _escape_milvus_string(v)
        item_len = len(escaped) + 4  # quotes + comma/space

        # Start a new batch when adding would exceed either cap.
        if cur and (len(cur) >= cap_items or (cur_len + item_len) > cap_chars):
            batches.append(cur)
            cur = []
            cur_len = overhead

        cur.append(v)
        cur_len += item_len

    if cur:
        batches.append(cur)

    return batches


def _milvus_value_expr(field: str, value: Any) -> str | None:
    if field in _MILVUS_NUMERIC_FIELDS:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return None
    if field in _MILVUS_STRING_FIELDS:
        return f"\"{_escape_milvus_string(str(value))}\""
    return None


def _milvus_in_list_expr(field: str, values: Any) -> str | None:
    if not isinstance(values, (list, tuple, set)):
        return None
    items: list[str] = []
    for v in values:
        expr = _milvus_value_expr(field, v)
        if expr is None:
            continue
        items.append(expr)
    if not items:
        return None
    return f"[{', '.join(items)}]"


def _indexed_metadata_value_expr(condition: Any) -> str | None:
    if isinstance(condition, dict):
        if "$eq" in condition:
            return _milvus_value_expr(_INDEXED_METADATA_VALUE_EXPR_FIELD, condition.get("$eq"))
        if "$in" in condition:
            return _milvus_in_list_expr(_INDEXED_METADATA_VALUE_EXPR_FIELD, condition.get("$in"))
        return None
    return _milvus_value_expr(_INDEXED_METADATA_VALUE_EXPR_FIELD, condition)


def _indexed_metadata_slot_expr(field: str, condition: Any) -> str | None:
    normalized_field = str(field or "").strip()
    if not normalized_field:
        return None

    value_expr = _indexed_metadata_value_expr(condition)
    if value_expr is None:
        return None

    value_op = "in" if isinstance(condition, dict) and "$in" in condition else "=="
    slot_parts: list[str] = []
    for key_field, value_field in _INDEXED_METADATA_SLOT_FIELD_PAIRS:
        key_expr = _milvus_value_expr(key_field, normalized_field)
        if key_expr is None:
            continue
        slot_parts.append(f"({key_field} == {key_expr} and {value_field} {value_op} {value_expr})")
    if not slot_parts:
        return None
    return f"({_MILVUS_EXPR_OR.join(slot_parts)})"


def _indexed_metadata_filter_exprs(indexed_filters: Any) -> list[str]:
    if not isinstance(indexed_filters, list):
        return []
    parts: list[str] = []
    for item in indexed_filters:
        if not isinstance(item, dict):
            continue
        expr = _indexed_metadata_slot_expr(
            field=str(item.get("field") or ""),
            condition=item.get("condition"),
        )
        if expr:
            parts.append(expr)
    return parts


def _normalize_milvus_filter_field(field: str) -> str | None:
    if "." in field:
        return None
    normalized = _MILVUS_FILTER_KEY_ALIASES.get(field, field)
    if normalized not in _MILVUS_ALLOWED_FILTER_FIELDS:
        return None
    if not _MILVUS_FIELD_NAME_RE.match(normalized):
        return None
    return normalized


def _milvus_scalar_clause_expr(field: str, value: Any) -> str | None:
    rhs = _milvus_value_expr(field, value)
    if rhs is None:
        return None
    return f"{field} == {rhs}"


def _milvus_operator_clause_expr(field: str, op: str, expected: Any) -> str | None:
    if op in ("$eq", "$ne"):
        rhs = _milvus_value_expr(field, expected)
        if rhs is None:
            return None
        operator = "==" if op == "$eq" else "!="
        return f"{field} {operator} {rhs}"

    if op in ("$gt", "$gte", "$lt", "$lte"):
        if field not in _MILVUS_NUMERIC_FIELDS:
            return None
        rhs = _milvus_value_expr(field, expected)
        if rhs is None:
            return None
        operator = {
            "$gt": ">",
            "$gte": ">=",
            "$lt": "<",
            "$lte": "<=",
        }.get(op)
        if operator is None:
            return None
        return f"{field} {operator} {rhs}"

    if op in ("$in", "$nin"):
        rhs = _milvus_in_list_expr(field, expected)
        if rhs is None:
            return None
        operator = "in" if op == "$in" else "not in"
        return f"{field} {operator} {rhs}"

    return None


def _milvus_condition_exprs(field: str, condition: Any) -> list[str]:
    if not isinstance(condition, dict):
        scalar_expr = _milvus_scalar_clause_expr(field, condition)
        return [scalar_expr] if scalar_expr else []

    parts: list[str] = []
    for op, expected in condition.items():
        clause = _milvus_operator_clause_expr(field, op, expected)
        if clause:
            parts.append(clause)
    return parts


def _build_milvus_metadata_expr(metadata_filter: dict[str, Any] | None) -> str | None:
    """Best-effort translation of metadata_filter into Milvus expr (AND semantics)."""
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return None

    parts: list[str] = []
    for raw_key, condition in metadata_filter.items():
        if not isinstance(raw_key, str):
            continue
        if raw_key == _INDEXED_METADATA_FILTERS_KEY:
            parts.extend(_indexed_metadata_filter_exprs(condition))
            continue

        key = _normalize_milvus_filter_field(raw_key)
        if key is None:
            continue
        parts.extend(_milvus_condition_exprs(key, condition))

    if not parts:
        return None
    expr = _MILVUS_EXPR_AND.join(parts)
    if len(expr) > _MILVUS_EXPR_MAX_CHARS:
        return None
    return expr


# ========= Embedding initialization ==========

def _init_embedding_model():
    """Initialize embedding model using app.rag.embedding module."""
    from app.rag.embedding import create_langchain_embeddings_from_config

    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    logger.info("[*] Loading embedding provider: %s", provider)

    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE

    return create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )


def _get_milvus_connection_args() -> dict[str, Any]:
    """Get Milvus connection configuration."""
    return {
        "host": settings.MILVUS_HOST,
        "port": str(settings.MILVUS_PORT),
        "user": settings.MILVUS_USER,
        "password": settings.MILVUS_PASSWORD,
    }


def _get_milvus_index_params() -> dict[str, Any]:
    """Get Milvus index configuration."""
    return MilvusConfig.get_index_params()


def _get_milvus_search_params() -> dict[str, Any]:
    """Get Milvus search configuration."""
    return MilvusConfig.get_search_params()


def _get_langchain_milvus_cls():  # noqa: ANN202
    from langchain_community.vectorstores import Milvus as LCMilvus

    return LCMilvus


def _milvus_store_field_name(store: Any, attr_name: str, default: str) -> str:
    return str(getattr(store, attr_name, default) or default).strip() or default


def _milvus_store_init_kwargs(store: Any) -> dict[str, Any]:
    init_kwargs: dict[str, Any] = {}
    partition_names = getattr(store, "partition_names", None)
    if partition_names:
        init_kwargs["partition_names"] = partition_names
    replica_number = getattr(store, "replica_number", None)
    if replica_number:
        init_kwargs["replica_number"] = replica_number
    store_timeout = getattr(store, "timeout", None)
    if store_timeout:
        init_kwargs["timeout"] = store_timeout
    return init_kwargs


def _prepare_adapter_vector_payload(
    items: list[dict[str, Any]],
    *,
    reserved_fields: set[str],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in items:
        ids.append(str(item["id"]))
        texts.append((item.get("content") or "")[:65_000])
        meta = dict(item.get("metadata") or {})
        for key in reserved_fields:
            meta.pop(key, None)
        meta.update(_flatten_indexed_metadata_slots(meta))
        metadatas.append(meta)
    return texts, ids, _normalize_milvus_metadata_batch(metadatas)


def _ensure_adapter_write_collection(
    store: Any,
    *,
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> Any:
    from pymilvus import Collection

    collection = getattr(store, "col", None)
    if isinstance(collection, Collection):
        return collection

    init_kwargs = _milvus_store_init_kwargs(store)
    init_kwargs.update({"embeddings": embeddings, "metadatas": metadatas})
    store._init(**init_kwargs)
    return getattr(store, "col", None)


def _append_store_metadata_columns(
    insert_dict: dict[str, list[Any]],
    *,
    store: Any,
    metadatas: list[dict[str, Any]],
) -> None:
    metadata_field = getattr(store, "_metadata_field", None)
    if metadata_field is not None:
        insert_dict[metadata_field] = metadatas
        return

    fields = list(getattr(store, "fields", []))
    primary_field = _milvus_store_field_name(store, "_primary_field", "id")
    allowed_fields = [field for field in fields if field != primary_field] if getattr(store, "auto_id", False) else fields
    for metadata in metadatas:
        for key, value in metadata.items():
            if key in allowed_fields:
                insert_dict.setdefault(key, []).append(value)


def _build_adapter_insert_dict(
    store: Any,
    *,
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
    ids: list[str],
) -> dict[str, list[Any]]:
    text_field = _milvus_store_field_name(store, "_text_field", "content")
    vector_field = _milvus_store_field_name(store, "_vector_field", "embedding")
    insert_dict: dict[str, list[Any]] = {
        text_field: texts,
        vector_field: embeddings,
    }
    if not getattr(store, "auto_id", False):
        insert_dict[_milvus_store_field_name(store, "_primary_field", "id")] = ids
    _append_store_metadata_columns(insert_dict, store=store, metadatas=metadatas)
    return insert_dict


def _invoke_milvus_batch_write(
    collection: Any,
    *,
    insert_list: list[list[Any]],
    timeout: float | None,
    upsert: bool,
    write_kwargs: dict[str, Any],
) -> list[str]:
    writer = getattr(collection, "upsert" if upsert else "insert")
    result = writer(insert_list, timeout=timeout, **write_kwargs)
    return [str(pk) for pk in result.primary_keys]


def _iter_milvus_batch_ranges(total_count: int, batch_size: int) -> range:
    return range(0, total_count, batch_size)


def _tenant_scoped_milvus_expr(tenant_id: str) -> str:
    expr = f'tenant_id == "{_escape_milvus_string(str(tenant_id))}"'
    if len(expr) > _MILVUS_EXPR_MAX_CHARS:
        raise MilvusMaintenanceError("semantic cache tenant scope expression exceeds Milvus limits")
    return expr


def _milvus_schema_field_names(collection: Any) -> set[str]:
    field_names: set[str] = set()
    schema = getattr(collection, "schema", None)
    fields = getattr(schema, "fields", None)
    if not isinstance(fields, (list, tuple)):
        return field_names
    for field in fields:
        field_name = str(getattr(field, "name", "") or "").strip()
        if field_name:
            field_names.add(field_name)
    return field_names


def _milvus_semantic_cache_output_fields(primary_field: str, field_names: set[str]) -> list[str]:
    output_fields = [primary_field]
    for field_name in ("tenant_id", "expires_at_epoch", "created_at_epoch"):
        if (not field_names) or field_name in field_names:
            output_fields.append(field_name)
    return output_fields


def _open_milvus_query_iterator(
    collection: Any,
    *,
    batch_size: int,
    expr: str,
    output_fields: list[str],
    timeout: float | None,
) -> Any:
    query_iterator = collection.query_iterator
    return query_iterator(
        batch_size=batch_size,
        limit=-1,
        expr=expr,
        output_fields=output_fields,
        timeout=timeout,
    )


def _milvus_iterator_next_callable(iterator: Any) -> Any:
    next_callable = getattr(iterator, "next", None)
    if callable(next_callable):
        return next_callable
    if hasattr(iterator, "__next__"):
        return iter(iterator).__next__
    return None


def _milvus_iterator_close_callable(iterator: Any) -> Any:
    close_callable = getattr(iterator, "close", None)
    return close_callable if callable(close_callable) else None


def _effective_milvus_write_batch_size(texts: list[str]) -> int:
    base = max(1, int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256))
    if not bool(getattr(settings, "VECTOR_WRITE_ADAPTIVE_BATCHING_ENABLED", True)):
        return base

    max_chars_per_batch = int(getattr(settings, "VECTOR_WRITE_BATCH_MAX_CHARS", 200_000) or 200_000)
    if max_chars_per_batch <= 0 or not texts:
        return base

    max_chunk_chars = max(len(text or "") for text in texts)
    if max_chunk_chars <= 0:
        return base

    budgeted = max(1, int(max_chars_per_batch // max_chunk_chars))
    return max(1, min(base, budgeted))


def _drop_indexed_metadata_slots(metadatas: list[dict[str, Any]]) -> None:
    for metadata in metadatas:
        for slot_field in _INDEXED_METADATA_SLOT_FIELDS:
            metadata.pop(slot_field, None)


def _record_milvus_write_compat_fallback(exc: Exception) -> None:
    global _MILVUS_WARNED_WRITE_COMPAT_FALLBACK
    if not _MILVUS_WARNED_WRITE_COMPAT_FALLBACK:
        logger.warning(
            "Milvus add_texts failed; retrying without optional indexed metadata slots. "
            "Legacy collections must be recreated if required routing fields are missing. err=%s",
            str(exc)[:200],
        )
        _MILVUS_WARNED_WRITE_COMPAT_FALLBACK = True
    try:
        from app.storage.vector.milvus_prometheus_metrics import observe_milvus_write_compat_fallback

        observe_milvus_write_compat_fallback(dropped_fields="indexed_meta_slots")
    except Exception as fallback_exc:
        logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, fallback_exc)


def _add_texts_with_milvus_compat(
    store: Any,
    *,
    texts: list[str],
    metadatas: list[dict[str, Any]],
    ids: list[str],
) -> list[str]:
    metadatas_norm = _normalize_milvus_metadata_batch(metadatas)
    try:
        pks = store.add_texts(texts=texts, metadatas=metadatas_norm, ids=ids)
    except Exception as exc:
        _record_milvus_write_compat_fallback(exc)
        _drop_indexed_metadata_slots(metadatas_norm)
        pks = store.add_texts(texts=texts, metadatas=metadatas_norm, ids=ids)
    return [str(pk) for pk in pks]


def _build_document_metadata(
    *,
    document_id: UUID,
    tenant_id: UUID,
    idx: int,
    meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    chunk_id = meta.get("chunk_id")
    vector_id = str(chunk_id) if chunk_id else f"{document_id}_{idx}"
    img_id = meta.get("img_id") or meta.get("image_id") or ""
    image_id = meta.get("image_id") or meta.get("img_id") or ""
    image_url = meta.get("image_url") or meta.get("img_url") or ""
    pipeline_hash = str(meta.get("pipeline_hash") or "")[:64]
    doc_pipeline_key = str(
        meta.get("doc_pipeline_key")
        or (f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id))
    )[:256]
    return vector_id, {
        "tenant_id": str(tenant_id),
        "dataset_id": str(meta.get("dataset_id") or "")[:_MILVUS_MAX_VARCHAR_BYTES],
        "embedding_space_hash": str(meta.get("embedding_space_hash") or "")[:128],
        "document_id": str(document_id),
        "chunk_index": int(meta.get("chunk_index", idx)),
        "chunk_id": str(chunk_id) if chunk_id else "",
        "pipeline_hash": pipeline_hash,
        "doc_pipeline_key": doc_pipeline_key,
        "page_number": int(meta.get("page") or meta.get("page_number") or 0),
        "source": str(meta.get("source", "unknown"))[:500],
        "file_type": str(meta.get("file_type", "unknown"))[:20],
        "img_id": str(img_id)[:500],
        "image_id": str(image_id)[:500],
        "image_url": str(image_url)[:2000],
        **_flatten_indexed_metadata_slots(meta),
    }


def _prepare_document_write_payload(
    documents: list[dict[str, Any]],
    *,
    document_id: UUID,
    tenant_id: UUID,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []
    for idx, doc in enumerate(documents):
        meta = doc.get("metadata") or {}
        vector_id, metadata = _build_document_metadata(
            document_id=document_id,
            tenant_id=tenant_id,
            idx=idx,
            meta=meta,
        )
        ids.append(vector_id)
        texts.append((doc.get("content") or "")[:65_535])
        metadatas.append(metadata)
    return texts, metadatas, ids


def _write_document_batches(
    store: Any,
    *,
    texts: list[str],
    metadatas: list[dict[str, Any]],
    ids: list[str],
    batch_size: int,
) -> list[str]:
    if batch_size >= len(texts):
        return _add_texts_with_milvus_compat(store, texts=texts, metadatas=metadatas, ids=ids)

    pks: list[str] = []
    for start in range(0, len(texts), batch_size):
        end = start + batch_size
        pks.extend(
            _add_texts_with_milvus_compat(
                store,
                texts=texts[start:end],
                metadatas=metadatas[start:end],
                ids=ids[start:end],
            )
        )
    return pks


def _normalize_milvus_query_ids(ids: list[str]) -> list[str]:
    return [str(value) for value in (ids or []) if isinstance(value, str) and value.strip()]


def _dedupe_milvus_query_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_ids: list[str] = []
    for value in ids:
        if value in seen:
            continue
        seen.add(value)
        unique_ids.append(value)
    return unique_ids


def _milvus_in_expr(field: str, values: list[str]) -> str | None:
    items = [f"\"{_escape_milvus_string(value)}\"" for value in values]
    if not items:
        return None
    return f"{field} in [{', '.join(items)}]"


def _query_milvus_rows_by_ids(
    collection: Any,
    *,
    ids: list[str],
    primary_field: str,
    output_fields: list[str],
    max_ids_per_query: int,
    timeout: float | None,
) -> list[dict[str, Any]] | None:
    query = collection.query
    rows_out: list[dict[str, Any]] = []
    for batch in _chunk_in_list_values(
        ids,
        field=primary_field,
        max_expr_chars=_MILVUS_EXPR_MAX_CHARS,
        max_items=int(max_ids_per_query or 0),
    ):
        expr = _milvus_in_expr(primary_field, batch)
        if expr is None:
            continue
        try:
            rows = query(expr=expr, output_fields=output_fields, timeout=timeout)
        except Exception:
            return None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                rows_out.append(row)
    return rows_out


def _coerce_milvus_vector(vec: Any) -> list[float] | None:
    if isinstance(vec, (list, tuple)):
        if all(isinstance(value, (int, float)) for value in vec):
            return [float(value) for value in vec]
        return None

    if not hasattr(vec, "tolist"):
        return None

    try:
        as_list = vec.tolist()
    except Exception:
        return None
    if isinstance(as_list, list) and all(isinstance(value, (int, float)) for value in as_list):
        return [float(value) for value in as_list]
    return None


class MilvusMaintenanceError(RuntimeError):
    """Raised when Milvus maintenance operations cannot be completed safely."""


class MilvusSemanticCacheMaintenanceIterator:
    """Small compatibility wrapper around Milvus query iterators."""

    def __init__(
        self,
        *,
        iterator: Any,
        next_batch: Any,
        close: Any,
        tenant_id: str,
        primary_field: str,
        collection_name: str,
    ) -> None:
        self._iterator = iterator
        self._next_batch = next_batch
        self._close = close
        self._tenant_id = tenant_id
        self._primary_field = primary_field
        self._collection_name = collection_name
        self._closed = False

    def next_batch(self) -> list[dict[str, Any]]:
        try:
            rows = self._next_batch()
        except StopIteration:
            return []
        except Exception as exc:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance iterator failed for collection={self._collection_name}: {type(exc).__name__}: {exc}"
            ) from exc

        if rows in (None, []):
            return []
        if not isinstance(rows, list):
            raise MilvusMaintenanceError(
                f"semantic cache maintenance iterator returned invalid rows for collection={self._collection_name}"
            )

        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get(self._primary_field)
            if rid is None:
                continue
            row_tenant_id = row.get("tenant_id")
            if str(row_tenant_id or "").strip() != self._tenant_id:
                raise MilvusMaintenanceError(
                    f"semantic cache maintenance row missing tenant scope for collection={self._collection_name}"
                )
            out.append(
                {
                    "id": str(rid),
                    "tenant_id": row_tenant_id,
                    "expires_at_epoch": row.get("expires_at_epoch"),
                    "created_at_epoch": row.get("created_at_epoch"),
                }
            )
        return out

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._close()
        except Exception as exc:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance iterator close failed for collection={self._collection_name}: {type(exc).__name__}: {exc}"
            ) from exc


# ========= Generic Milvus adapter ==========

class MilvusAdapter:
    """
    Generic Milvus adapter that supports custom collections.

    Used for KG entity/event vector storage with multiple collections.
    """

    def __init__(
        self,
        collection_name: str,
        vector_field: str = "embedding",
        text_field: str = "content",
    ):
        self.collection_name = collection_name
        self.vector_field = vector_field
        self.text_field = text_field
        self._store = None
        self._embedding_model = None

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = _init_embedding_model()

        lc_milvus = _get_langchain_milvus_cls()
        self._store = lc_milvus(
            embedding_function=self._embedding_model,
            collection_name=self.collection_name,
            connection_args=_get_milvus_connection_args(),
            index_params=_get_milvus_index_params(),
            search_params=_get_milvus_search_params(),
            auto_id=False,
            primary_field="id",
            text_field=self.text_field,
            vector_field=self.vector_field,
        )

    def _require_store(self):
        self._ensure_store()
        if self._store is None:
            raise RuntimeError(f"Milvus store is not initialized for collection={self.collection_name}")
        return self._store

    def add_vectors(
        self,
        items: list[dict[str, Any]],
        embeddings: list[list[float]] | None = None,
        *,
        batch_size: int = 1000,
        timeout: float | None = None,
        upsert: bool = True,
        **kwargs: Any,
    ) -> list[str]:
        """
        Batch write vectors (supports directly writing pre-computed embeddings to avoid duplicate embedding).

        Args:
            items: [{"id": str, "content": str, "metadata": dict}]
            embeddings: Optional, pre-computed vectors (List[List[float]]), corresponding to items.
                - When None: LangChain Embeddings auto-generates based on content
                - When not None: directly writes to Milvus (insert/upsert)
            batch_size: write batch size
            timeout: Milvus timeout
            upsert: True uses Milvus upsert; False uses insert

        Returns:
            List of vector IDs
        """
        if not items:
            return []

        store = self._require_store()
        reserved_fields = {
            _milvus_store_field_name(store, "_primary_field", "id"),
            _milvus_store_field_name(store, "_text_field", self.text_field),
            _milvus_store_field_name(store, "_vector_field", self.vector_field),
        }
        texts, ids, metadatas = _prepare_adapter_vector_payload(items, reserved_fields=reserved_fields)

        # Default path: let LangChain generate embeddings then insert.
        if embeddings is None:
            pks = store.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids,
                batch_size=batch_size,
                timeout=timeout,
                **kwargs,
            )
            return [str(pk) for pk in pks]

        if len(embeddings) != len(items):
            raise ValueError("embeddings length must match items length")

        from pymilvus import Collection, MilvusException

        collection = _ensure_adapter_write_collection(
            store,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        insert_dict = _build_adapter_insert_dict(
            store,
            texts=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        total_count = len(embeddings)
        pks: list[str] = []
        if not isinstance(collection, Collection):
            raise RuntimeError(f"Milvus collection is not initialized for collection={self.collection_name}")
        field_order = list(getattr(store, "fields", []))
        eff_timeout = getattr(store, "timeout", None) or timeout
        for start in _iter_milvus_batch_ranges(total_count, batch_size):
            end = min(start + batch_size, total_count)
            insert_list = [insert_dict[field][start:end] for field in field_order if field in insert_dict]
            try:
                pks.extend(
                    _invoke_milvus_batch_write(
                        collection,
                        insert_list=insert_list,
                        timeout=eff_timeout,
                        upsert=upsert,
                        write_kwargs=kwargs,
                    )
                )
            except MilvusException:
                logger.exception(
                    "Failed to write vectors batch: %s/%s collection=%s",
                    start,
                    total_count,
                    self.collection_name,
                )
                raise

        try:
            collection.flush()
        except MilvusException:
            logger.exception("Failed to flush vector writes collection=%s", self.collection_name)
            raise

        return pks

    def delete(self, ids: list[str]) -> None:
        """Delete vectors with specified IDs."""
        if not ids:
            return
        store = self._require_store()
        if not _ensure_milvus_collection_loaded(store):
            return
        store.delete(ids)

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        """Delete all vectors for a document from this collection."""
        store = self._require_store()
        if not _ensure_milvus_collection_loaded(store):
            return
        parts = []
        if tenant_id:
            parts.append(f'tenant_id == "{_escape_milvus_string(str(tenant_id))}"')
        parts.append(f'document_id == "{_escape_milvus_string(str(document_id))}"')
        expr = _MILVUS_EXPR_AND.join(parts)
        # Delete is already expressed at the collection layer; flushing here turns
        # document teardown into a blocking durability wait and does not improve
        # request correctness for our lifecycle flow.
        store.delete(expr=expr)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        """Delete vectors for a document with an additional safe metadata filter."""
        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if not metadata_expr:
            return
        store = self._require_store()
        if not _ensure_milvus_collection_loaded(store):
            return
        parts = []
        if tenant_id:
            parts.append(f'tenant_id == "{_escape_milvus_string(str(tenant_id))}"')
        parts.append(f'document_id == "{_escape_milvus_string(str(document_id))}"')
        base_expr = _MILVUS_EXPR_AND.join(parts)
        expr = f"({base_expr}) and ({metadata_expr})"
        # Same rationale as delete_by_document_id(): avoid synchronous flush on teardown.
        store.delete(expr=expr)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        expr: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Vector similarity search.

        Args:
            query_vector: Query vector
            top_k: Number of results to return
            expr: Filter expression

        Returns:
            List of search results
        """
        self._require_store()

        supported_filter = _sanitize_milvus_metadata_filter(metadata_filter)
        metadata_expr = _build_milvus_metadata_expr(supported_filter)
        metadata_expr_fallback = False
        if expr and metadata_expr:
            combined_expr = f"({expr}) and ({metadata_expr})"
        else:
            combined_expr = expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score_by_vector(
                embedding=query_vector,
                k=top_k,
                expr=combined_expr,
            )
        except Exception:
            # Fallback: ignore pushdown on schema/expr mismatch; still apply client-side filtering.
            metadata_expr_fallback = bool(metadata_expr)
            results = self._store.similarity_search_with_score_by_vector(
                embedding=query_vector,
                k=top_k,
                expr=expr,
            )
        client_filter = (
            _milvus_scalar_client_filter_spec(supported_filter)
            if metadata_expr_fallback
            else _milvus_client_filter_spec(supported_filter)
        )
        out: list[dict[str, Any]] = []
        for doc, score in results:
            meta = _rehydrate_indexed_metadata_slots(doc.metadata or {})
            if client_filter and not _match_metadata_filter(meta, client_filter):
                continue
            out.append(
                {
                    "id": doc.id,
                    "metadata": meta,
                    "score": float(score),
                    "content": doc.page_content,
                }
            )
        return out

    def search_native_hybrid(
        self,
        *,
        query_vector: list[float],
        sparse_query_vector: Any,
        top_k: int = 10,
        expr: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Best-effort Milvus native dense+sparse search contract.

        Notes:
        - This method only uses native hybrid when the underlying store exposes an
          explicit hybrid-search hook.
        - When the current Milvus/LangChain runtime does not expose such a hook, we
          raise ``NotImplementedError`` so the caller can deterministically fall back
          to the existing channel-fusion path without pretending native support exists.
        """
        self._require_store()

        supported_filter = _sanitize_milvus_metadata_filter(metadata_filter)
        metadata_expr = _build_milvus_metadata_expr(supported_filter)
        metadata_expr_fallback = False
        if expr and metadata_expr:
            combined_expr = f"({expr}) and ({metadata_expr})"
        else:
            combined_expr = expr or metadata_expr

        sparse_payload = sparse_query_vector
        if hasattr(sparse_query_vector, "weights"):
            sparse_payload = sparse_query_vector.weights

        def _invoke(store_expr: str | None):  # noqa: ANN202
            if hasattr(self._store, "similarity_search_with_hybrid_score_by_vector"):
                return self._store.similarity_search_with_hybrid_score_by_vector(
                    embedding=query_vector,
                    sparse_embedding=sparse_payload,
                    k=top_k,
                    expr=store_expr,
                )
            if hasattr(self._store, "hybrid_search_with_score"):
                return self._store.hybrid_search_with_score(
                    dense_embedding=query_vector,
                    sparse_embedding=sparse_payload,
                    k=top_k,
                    expr=store_expr,
                )
            raise NotImplementedError("milvus_native_hybrid_unsupported")

        try:
            results = _invoke(combined_expr)
        except NotImplementedError:
            raise
        except Exception:
            metadata_expr_fallback = bool(metadata_expr)
            results = _invoke(expr)

        client_filter = (
            _milvus_scalar_client_filter_spec(supported_filter)
            if metadata_expr_fallback
            else _milvus_client_filter_spec(supported_filter)
        )
        out: list[dict[str, Any]] = []
        for doc, score in results:
            meta = _rehydrate_indexed_metadata_slots(doc.metadata or {})
            if client_filter and not _match_metadata_filter(meta, client_filter):
                continue
            out.append(
                {
                    "id": doc.id,
                    "metadata": meta,
                    "score": float(score),
                    "content": doc.page_content,
                }
            )
        return out

    def open_semantic_cache_maintenance_iterator(
        self,
        *,
        tenant_id: str,
        batch_size: int = 1000,
        timeout: float | None = None,
    ) -> MilvusSemanticCacheMaintenanceIterator:
        store = self._require_store()
        col = getattr(store, "col", None)
        if col is None or not hasattr(col, "query_iterator"):
            raise MilvusMaintenanceError(
                f"semantic cache maintenance requires Milvus query iterator support for collection={self.collection_name}"
            )

        primary_field = _milvus_store_field_name(store, "_primary_field", "id")
        batch_size_i = max(1, int(batch_size or 0))
        field_names = _milvus_schema_field_names(col)
        if field_names and "tenant_id" not in field_names:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance requires tenant_id metadata in collection={self.collection_name}"
            )

        output_fields = _milvus_semantic_cache_output_fields(primary_field, field_names)
        expr = _tenant_scoped_milvus_expr(tenant_id)

        try:
            iterator = _open_milvus_query_iterator(
                col,
                batch_size=batch_size_i,
                expr=expr,
                output_fields=output_fields,
                timeout=timeout,
            )
        except Exception as exc:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance query iterator failed for collection={self.collection_name}: {type(exc).__name__}: {exc}"
            ) from exc

        next_batch = _milvus_iterator_next_callable(iterator)
        if next_batch is None:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance iterator is unsupported for collection={self.collection_name}"
            )
        close_callable = _milvus_iterator_close_callable(iterator)
        if close_callable is None:
            raise MilvusMaintenanceError(
                f"semantic cache maintenance iterator close is unsupported for collection={self.collection_name}"
            )
        return MilvusSemanticCacheMaintenanceIterator(
            iterator=iterator,
            next_batch=next_batch,
            close=close_callable,
            tenant_id=str(tenant_id),
            primary_field=primary_field,
            collection_name=self.collection_name,
        )


_milvus_adapter_cache: dict[tuple[str, str, str], MilvusAdapter] = {}
_milvus_adapter_cache_lock = threading.Lock()


def resolve_collection_name(preferred: str) -> str:
    """Resolve canonical Milvus collection name."""
    return preferred


def get_milvus_adapter(
    collection_name: str,
    *,
    vector_field: str = "embedding",
    text_field: str = "content",
) -> MilvusAdapter:
    key = (collection_name, vector_field, text_field)
    with _milvus_adapter_cache_lock:
        cached = _milvus_adapter_cache.get(key)
        if cached is not None:
            return cached
        adapter = MilvusAdapter(collection_name=collection_name, vector_field=vector_field, text_field=text_field)
        _milvus_adapter_cache[key] = adapter
        return adapter


# ========= Document vector store (singleton) ==========

class MilvusVectorStore:
    """
    Milvus vector store service (document vectors, singleton).

    Used for knowledge base document vectors with a fixed collection name.
    """

    _instance: Optional["MilvusVectorStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self._embedding_model = None
        self._store = None
        self._embedding_space_hash = ""
        self._store_lock = threading.RLock()

    @staticmethod
    def _current_embedding_space_hash() -> str:
        try:
            from app.rag.embedding.utils import current_embedding_space_hash

            return str(current_embedding_space_hash() or "").strip()
        except Exception:
            return ""

    def _init_embedding_model(self):
        """Initialize embedding model."""
        return _init_embedding_model()

    def get_embedding_model(self):  # noqa: ANN201
        with self._store_lock:
            current_space = self._current_embedding_space_hash()
            if self._embedding_model is not None and self._embedding_space_hash and current_space != self._embedding_space_hash:
                logger.info(
                    "Embedding space changed; rebuilding Milvus embedding client (%s -> %s)",
                    self._embedding_space_hash,
                    current_space,
                )
                self._embedding_model = None
                self._store = None
            if self._embedding_model is None:
                self._embedding_model = _init_embedding_model()
                self._embedding_space_hash = current_space
            return self._embedding_model

    def _ensure_store(self):
        with self._store_lock:
            current_space = self._current_embedding_space_hash()
            if self._store is not None and self._embedding_space_hash and current_space != self._embedding_space_hash:
                logger.info(
                    "Embedding space changed; rebuilding Milvus vector store adapter (%s -> %s)",
                    self._embedding_space_hash,
                    current_space,
                )
                self._store = None
                self._embedding_model = None

            if self._store is not None:
                return

            embedding_model = self.get_embedding_model()

            lc_milvus = _get_langchain_milvus_cls()
            self._store = lc_milvus(
                embedding_function=embedding_model,
                collection_name=settings.MILVUS_COLLECTION_NAME,
                connection_args=_get_milvus_connection_args(),
                index_params=_get_milvus_index_params(),
                search_params=_get_milvus_search_params(),
                auto_id=False,
                primary_field="id",
                text_field="content",
                vector_field="embedding",
            )
            self._embedding_space_hash = current_space

    def _require_store(self):
        self._ensure_store()
        if self._store is None:
            raise RuntimeError("Milvus vector store is not initialized")
        return self._store

    def _build_expr(
        self,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
    ) -> str | None:
        """Build a Milvus filter expression."""
        expr_parts: list[str] = []
        if tenant_id:
            expr_parts.append(f'tenant_id == "{str(tenant_id)}"')
        if document_ids:
            max_doc_ids = int(getattr(settings, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0)
            if max_doc_ids > 0 and len(document_ids) > max_doc_ids:
                # Fallback to tenant-only expr; caller/retriever can still post-filter by doc_ids.
                logger.info(
                    "Skipping Milvus document_id pushdown (too many ids: %s > %s)",
                    len(document_ids),
                    max_doc_ids,
                )
            else:
                doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
                expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        return _MILVUS_EXPR_AND.join(expr_parts) if expr_parts else None

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[str]:
        """Add document chunks to Milvus (returns vector id list)."""
        store = self._require_store()
        texts, metadatas, ids = _prepare_document_write_payload(
            documents,
            document_id=document_id,
            tenant_id=tenant_id,
        )
        batch_size = _effective_milvus_write_batch_size(texts)
        return _write_document_batches(
            store,
            texts=texts,
            metadatas=metadatas,
            ids=ids,
            batch_size=batch_size,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search (text query)."""
        self._require_store()

        supported_filter = _sanitize_milvus_metadata_filter(
            metadata_filter,
            allowed_fields=set(_DOC_VECTOR_METADATA_FIELDS),
        )
        base_expr = self._build_expr(document_ids=document_ids, tenant_id=tenant_id)
        metadata_expr = _build_milvus_metadata_expr(supported_filter)
        metadata_expr_fallback = False
        if base_expr and metadata_expr:
            combined_expr = f"({base_expr}) and ({metadata_expr})"
        else:
            combined_expr = base_expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=combined_expr)
        except Exception as exc:
            # Fallback for legacy collections / unsupported expr clauses.
            metadata_expr_fallback = bool(metadata_expr)
            global _MILVUS_WARNED_SEARCH_EXPR_FALLBACK
            if not _MILVUS_WARNED_SEARCH_EXPR_FALLBACK:
                logger.warning(
                    "Milvus search expr failed; retrying without metadata expr pushdown. err=%s",
                    str(exc)[:200],
                )
                _MILVUS_WARNED_SEARCH_EXPR_FALLBACK = True
            try:
                from app.storage.vector.milvus_prometheus_metrics import observe_milvus_search_expr_fallback

                observe_milvus_search_expr_fallback(
                    has_metadata_expr=bool(metadata_expr),
                    has_base_expr=bool(base_expr),
                )
            except Exception as exc:
                logger.debug(_MILVUS_FALLBACK_LOG_MESSAGE, exc)
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=base_expr)

        client_filter = (
            _milvus_scalar_client_filter_spec(supported_filter)
            if metadata_expr_fallback
            else _milvus_client_filter_spec(supported_filter)
        )
        formatted: list[dict[str, Any]] = []
        for doc, score in results:
            if score < score_threshold:
                continue
            meta = _rehydrate_indexed_metadata_slots(doc.metadata or {})
            if client_filter and not _match_metadata_filter(meta, client_filter):
                continue
            chunk_id = meta.get("chunk_id")
            out_meta = {
                "tenant_id": meta.get("tenant_id"),
                "dataset_id": meta.get("dataset_id"),
                "embedding_space_hash": meta.get("embedding_space_hash"),
                "document_id": meta.get("document_id"),
                "source": meta.get("source", "unknown"),
                "page": meta.get("page_number"),
                "page_number": meta.get("page_number"),
                "chunk_index": meta.get("chunk_index"),
                "chunk_id": chunk_id,
                "pipeline_hash": meta.get("pipeline_hash"),
                "doc_pipeline_key": meta.get("doc_pipeline_key"),
                "img_id": meta.get("img_id") or meta.get("image_id"),
                "image_id": meta.get("image_id") or meta.get("img_id"),
                "image_url": meta.get("image_url") or meta.get("img_url"),
                "score": float(score),
            }
            indexed_metadata = meta.get(_INDEXED_METADATA_VIEW_KEY)
            if isinstance(indexed_metadata, dict) and indexed_metadata:
                out_meta[_INDEXED_METADATA_VIEW_KEY] = indexed_metadata
            formatted.append(
                {
                    "chunk_id": chunk_id,
                    "content": doc.page_content,
                    "metadata": out_meta,
                    "score": float(score),
                }
            )
            if len(formatted) >= top_k:
                break

        return formatted

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:
        """Delete all vectors for a given document."""
        store = self._require_store()
        if not _ensure_milvus_collection_loaded(store):
            return

        expr = self._build_expr(document_ids=[document_id], tenant_id=tenant_id)
        if expr:
            # Keep delete non-blocking; the collection delete itself is sufficient here.
            store.delete(expr=expr)

    def delete_by_document_id_and_filter(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        """
        Delete vectors for a given document, scoped by a metadata_filter (best-effort).

        Safety notes:
        - If the filter cannot be translated into a safe Milvus expr, this is a no-op (never "delete all").
        - Caller can still fall back to full delete_by_document_id when appropriate.
        """
        store = self._require_store()
        if not _ensure_milvus_collection_loaded(store):
            return

        base_expr = self._build_expr(document_ids=[document_id], tenant_id=tenant_id)
        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if not metadata_expr:
            return

        expr = f"({base_expr}) and ({metadata_expr})" if base_expr else metadata_expr
        # Avoid an explicit flush here to prevent teardown from waiting on Milvus compaction.
        store.delete(expr=expr)

    def get_collection_count(self) -> int:
        """Return document count in the vector collection."""
        self._require_store()
        try:
            return int(self._store.col.num_entities)  # type: ignore[union-attr]
        except Exception:
            return 0

    def fetch_existing_ids(
        self,
        ids: list[str],
        *,
        max_ids_per_query: int = 256,
        timeout: float | None = None,
    ) -> set[str]:
        """
        Best-effort existence check for a list of vector primary keys.

        Used by index audit / troubleshooting to detect missing vectors when the DB
        still references a vector_id.

        Notes:
        - Uses Milvus `query()` with an `id in [...]` expr.
        - Batches by both item count and expr length to reduce server-side rejects.
        - Returns an empty set on any failure (audit should degrade gracefully).
        """
        raw_ids = _normalize_milvus_query_ids(ids)
        if not raw_ids:
            return set()

        store = self._require_store()
        col = getattr(store, "col", None)
        if col is None or not hasattr(col, "query"):
            return set()

        primary_field = _milvus_store_field_name(store, "_primary_field", "id")
        rows = _query_milvus_rows_by_ids(
            col,
            ids=_dedupe_milvus_query_ids(raw_ids),
            primary_field=primary_field,
            output_fields=[primary_field],
            max_ids_per_query=max_ids_per_query,
            timeout=timeout,
        )
        if rows is None:
            return set()

        existing: set[str] = set()
        for row in rows:
            val = row.get(primary_field)
            if val is not None:
                existing.add(str(val))
        return existing

    def fetch_vectors_by_ids(
        self,
        ids: list[str],
        *,
        max_ids_per_query: int = 128,
        timeout: float | None = None,
    ) -> dict[str, list[float]]:
        """
        Best-effort fetch of stored vectors by primary key.

        Used by offline diagnostics (e.g. embedding drift monitor). This is intentionally
        bounded and fail-open: returns an empty mapping on any failure.

        Notes:
        - Uses Milvus `query()` with an `id in [...]` expr.
        - Batches by both item count and expr length to reduce server-side rejects.
        """
        raw_ids = _normalize_milvus_query_ids(ids)
        if not raw_ids:
            return {}

        store = self._require_store()
        col = getattr(store, "col", None)
        if col is None or not hasattr(col, "query"):
            return {}

        primary_field = _milvus_store_field_name(store, "_primary_field", "id")
        vector_field = _milvus_store_field_name(store, "_vector_field", "embedding")
        rows = _query_milvus_rows_by_ids(
            col,
            ids=_dedupe_milvus_query_ids(raw_ids),
            primary_field=primary_field,
            output_fields=[primary_field, vector_field],
            max_ids_per_query=max_ids_per_query,
            timeout=timeout,
        )
        if rows is None:
            return {}

        out: dict[str, list[float]] = {}
        for row in rows:
            pk = row.get(primary_field)
            vec = row.get(vector_field)
            if pk is None or vec is None:
                continue

            vector = _coerce_milvus_vector(vec)
            if vector:
                out[str(pk)] = vector

        return out

    def list_ids_by_dataset(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        limit: int = 2000,
        offset: int = 0,
        timeout: float | None = None,
    ) -> list[str]:
        """
        Best-effort listing of vector ids for a dataset.

        This is intentionally bounded (limit/offset) and should only be used for
        troubleshooting/audits (not hot path retrieval).
        """
        self._require_store()

        col = getattr(self._store, "col", None)
        if col is None or not hasattr(col, "query"):
            return []

        primary_field = str(getattr(self._store, "_primary_field", "id") or "id").strip() or "id"

        lim = max(0, int(limit or 0))
        if lim <= 0:
            return []
        off = max(0, int(offset or 0))

        expr = (
            f'tenant_id == "{_escape_milvus_string(str(tenant_id))}" '
            f'and dataset_id == "{_escape_milvus_string(str(dataset_id))}"'
        )
        if len(expr) > _MILVUS_EXPR_MAX_CHARS:
            return []

        try:
            rows = col.query(  # type: ignore[call-arg]
                expr=expr,
                output_fields=[primary_field],
                limit=lim,
                offset=off,
                timeout=timeout,
            )
        except Exception:
            return []

        out: list[str] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            v = row.get(primary_field)
            if v is None:
                continue
            out.append(str(v))

        return out


# ========= Global instances ==========

# Document vector store (singleton)
milvus_store = MilvusVectorStore()
