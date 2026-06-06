from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.rag.pipeline_plugins.contracts import (
    PipelinePluginContractError,
    apply_metadata_schema_views,
    apply_retrieval_text_schema,
    strip_reserved_platform_metadata_views,
    validate_documents_metadata,
    validate_kg_events_metadata,
    validate_no_reserved_platform_metadata_views,
)
from app.rag.pipeline_plugins.refs import clean_python_plugin_ref
from app.rag.pipeline_plugins.registry import (
    is_registered_plugin_ref,
    parse_registered_plugin_ref,
    resolve_registered_plugin_callable,
    resolve_registered_plugin_descriptor,
)
from app.types.indexing import EventEntityInput, IndexKind, IndexRecord

_DEFAULT_GOVERNANCE_FUNC = "govern_documents"
_DEFAULT_CHUNKING_FUNC = "chunk_documents"
_DEFAULT_KG_FUNC = "build_kg_events"


class PythonPipelinePluginError(RuntimeError):
    """Raised when a configured Python pipeline plugin cannot be loaded or run."""


def _split_plugin_ref(plugin_ref: str, *, default_function: str) -> tuple[str, str]:
    try:
        ref = clean_python_plugin_ref(
            plugin_ref,
            invalid_message="python plugin ref must be module or module:function",
            file_path_message="python plugin ref must be module or module:function",
            disabled_import_message=(
                "python plugin import refs are disabled; use a registered plugin:<id>@<version>:<stage> ref "
                "or configure PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES"
            ),
        )
    except ValueError as exc:
        raise PythonPipelinePluginError(str(exc)) from exc
    if not ref:
        raise PythonPipelinePluginError("python plugin ref is empty")

    module_name, sep, function_name = ref.partition(":")
    if not sep:
        function_name = default_function
    return module_name, function_name


def _context_plugin_directories(context: dict[str, Any] | None) -> list[Any] | None:
    raw = (context or {}).get("plugin_directories")
    if raw is None:
        raw = (context or {}).get("plugin_dirs")
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


def _context_require_test_report(context: dict[str, Any] | None) -> bool | None:
    if not context:
        return None
    raw = context.get("require_test_report")
    if raw is not None:
        return bool(raw)
    # Local contract tests pass explicit plugin directories before a report exists.
    # Production ingestion does not pass this context and keeps the settings default.
    if _context_plugin_directories(context):
        return False
    return None


def _load_plugin_callable(
    plugin_ref: str,
    *,
    default_function: str,
    directories: list[Any] | None = None,
    require_test_report: bool | None = None,
) -> Callable[..., Any]:
    if is_registered_plugin_ref(plugin_ref):
        return resolve_registered_plugin_callable(
            plugin_ref,
            directories=directories,
            require_test_report=require_test_report,
        )

    module_name, function_name = _split_plugin_ref(plugin_ref, default_function=default_function)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        raise PythonPipelinePluginError(f"failed to import python plugin module '{module_name}': {exc}") from exc

    func = getattr(module, function_name, None)
    if not callable(func):
        raise PythonPipelinePluginError(f"python plugin '{module_name}' has no callable '{function_name}'")
    return func


def _ensure_registered_plugin_stage(plugin_ref: str, *, expected_stage: str) -> None:
    if not is_registered_plugin_ref(plugin_ref):
        return
    _plugin_id, _version, stage = parse_registered_plugin_ref(plugin_ref)
    if stage != expected_stage:
        raise PythonPipelinePluginError(f"registered plugin ref must target the {expected_stage} stage")


def _apply_registered_plugin_contracts(
    documents: list[Document],
    *,
    plugin_ref: str,
    stage: str,
    context: dict[str, Any],
) -> list[Document]:
    try:
        for document in documents:
            validate_no_reserved_platform_metadata_views(document.metadata, field_label=f"{stage} plugin metadata")
    except PipelinePluginContractError as exc:
        raise PythonPipelinePluginError(str(exc)) from exc
    if not is_registered_plugin_ref(plugin_ref):
        return documents
    try:
        descriptor = resolve_registered_plugin_descriptor(
            plugin_ref,
            directories=_context_plugin_directories(context),
            require_test_report=_context_require_test_report(context),
        )
        validation = validate_documents_metadata(
            documents,
            metadata_schema=descriptor.metadata_schema,
            stage=stage,
        )
    except PipelinePluginContractError as exc:
        raise PythonPipelinePluginError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise PythonPipelinePluginError(f"failed to validate plugin contract: {exc}") from exc
    if not validation.get("ok"):
        errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
        first = errors[0] if errors else {}
        field = first.get("field") if isinstance(first, dict) else None
        reason = first.get("reason") if isinstance(first, dict) else None
        raise PythonPipelinePluginError(f"plugin metadata contract failed for {field or 'metadata'}: {reason or 'invalid'}")
    try:
        documents = apply_metadata_schema_views(
            documents,
            metadata_schema=descriptor.metadata_schema,
            stage=stage,
        )
        return apply_retrieval_text_schema(
            documents,
            retrieval_text_schema=descriptor.retrieval_text_schema,
            stage=stage,
        )
    except PipelinePluginContractError as exc:
        raise PythonPipelinePluginError(str(exc)) from exc


def _apply_registered_kg_plugin_contracts(
    events: list[IndexRecord],
    *,
    plugin_ref: str,
    context: dict[str, Any],
) -> list[IndexRecord]:
    if not is_registered_plugin_ref(plugin_ref):
        return events
    try:
        descriptor = resolve_registered_plugin_descriptor(
            plugin_ref,
            directories=_context_plugin_directories(context),
            require_test_report=_context_require_test_report(context),
        )
        validation = validate_kg_events_metadata(events, metadata_schema=descriptor.metadata_schema)
    except PipelinePluginContractError as exc:
        raise PythonPipelinePluginError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise PythonPipelinePluginError(f"failed to validate plugin KG contract: {exc}") from exc
    if not validation.get("ok"):
        errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
        first = errors[0] if errors else {}
        field = first.get("field") if isinstance(first, dict) else None
        reason = first.get("reason") if isinstance(first, dict) else None
        raise PythonPipelinePluginError(f"plugin KG metadata contract failed for {field or 'metadata'}: {reason or 'invalid'}")
    return events


def _invoke_plugin(
    func: Callable[..., Any],
    *,
    documents: list[Document],
    params: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return func(documents, params, context)

    kwargs: dict[str, Any] = {}
    positional: list[Any] = []
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
    for name, param in sig.parameters.items():
        if name in {"documents", "items", "docs"}:
            kwargs[name] = documents
        elif name == "params":
            kwargs[name] = params
        elif name == "context":
            kwargs[name] = context
        elif name == "chunk_size":
            kwargs[name] = context.get("chunk_size")
        elif name == "chunk_overlap":
            kwargs[name] = context.get("chunk_overlap")
        elif name == "stage":
            kwargs[name] = context.get("stage")
        elif param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            if not positional and param.default is inspect.Parameter.empty:
                positional.append(documents)
        elif accepts_kwargs:
            continue

    if kwargs:
        return func(**kwargs)
    return func(*positional) if positional else func()


def _coerce_metadata(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_document(item: Any, *, stage: str, plugin_ref: str, index: int) -> Document:
    if isinstance(item, Document):
        meta = dict(item.metadata or {})
        meta.setdefault(f"{stage}_python_plugin", plugin_ref)
        return Document(page_content=item.page_content or "", metadata=meta, id=getattr(item, "id", None))

    if isinstance(item, str):
        return Document(page_content=item, metadata={f"{stage}_python_plugin": plugin_ref})

    if isinstance(item, dict):
        content = item.get("page_content")
        if content is None:
            content = item.get("content")
        if content is None:
            content = item.get("text")
        meta = _coerce_metadata(item.get("metadata"))
        meta.setdefault(f"{stage}_python_plugin", plugin_ref)
        doc_id = item.get("id")
        return Document(page_content=str(content or ""), metadata=meta, id=doc_id)

    raise PythonPipelinePluginError(f"python plugin returned unsupported item at index {index}: {type(item).__name__}")


def _coerce_documents(result: Any, *, stage: str, plugin_ref: str) -> list[Document]:
    if result is None:
        return []
    if isinstance(result, Document):
        return [_coerce_document(result, stage=stage, plugin_ref=plugin_ref, index=0)]
    if isinstance(result, (str, bytes)):
        text = result.decode("utf-8", "replace") if isinstance(result, bytes) else result
        return [_coerce_document(text, stage=stage, plugin_ref=plugin_ref, index=0)]
    if not isinstance(result, Iterable):
        raise PythonPipelinePluginError(f"python plugin returned unsupported result: {type(result).__name__}")

    out: list[Document] = []
    for idx, item in enumerate(result):
        doc = _coerce_document(item, stage=stage, plugin_ref=plugin_ref, index=idx)
        if (doc.page_content or "").strip():
            out.append(doc)
    return out


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return UUID(text)
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_vector(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except Exception:
            return None
    return out or None


def _coerce_event_entity(item: Any, *, event_index: int, entity_index: int) -> EventEntityInput | None:
    if not isinstance(item, dict):
        raise PythonPipelinePluginError(
            f"kg plugin returned unsupported entity at event {event_index}, index {entity_index}: {type(item).__name__}"
        )
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    normalized = str(item.get("normalized_name") or item.get("normalized") or name).strip() or name
    ent_type = str(item.get("type") or "unknown").strip() or "unknown"
    return EventEntityInput(
        name=name,
        normalized_name=normalized,
        type=ent_type,
        description=(str(item.get("description") or "").strip() or None),
        vector=_coerce_vector(item.get("vector")),
        role=(str(item.get("role") or "").strip() or None),
        evidence_quote=(str(item.get("evidence_quote") or "").strip() or None),
        evidence_source=(str(item.get("evidence_source") or "").strip() or None),
        evidence_start_char=_coerce_int(item.get("evidence_start_char")),
        evidence_end_char=_coerce_int(item.get("evidence_end_char")),
    )


def _source_metadata(documents: list[Document], index: int) -> dict[str, Any]:
    if not documents:
        return {}
    if index < len(documents):
        return dict(documents[index].metadata or {})
    return dict(documents[-1].metadata or {})


def _source_document(documents: list[Document], index: int) -> Document | None:
    if not documents:
        return None
    if index < len(documents):
        return documents[index]
    return documents[-1]


def _iter_kg_result(result: Any) -> list[Any]:
    if result is None:
        return []
    if isinstance(result, (dict, IndexRecord)):
        return [result]
    if isinstance(result, (str, bytes)):
        raise PythonPipelinePluginError("kg plugin must return event objects, not raw text")
    if not isinstance(result, Iterable):
        raise PythonPipelinePluginError(f"kg plugin returned unsupported result: {type(result).__name__}")
    return list(result)


def _coerce_kg_event(
    item: Any,
    *,
    documents: list[Document],
    plugin_ref: str,
    index: int,
) -> IndexRecord | None:
    if isinstance(item, IndexRecord):
        if item.kind != IndexKind.EVENT:
            raise PythonPipelinePluginError(f"kg plugin returned non-event IndexRecord at index {index}")
        return item
    if not isinstance(item, dict):
        raise PythonPipelinePluginError(f"kg plugin returned unsupported event at index {index}: {type(item).__name__}")

    source_index = _coerce_int(item.get("source_index"))
    if source_index is None:
        source_index = index
    meta = _source_metadata(documents, source_index)
    source_doc = _source_document(documents, source_index)

    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    content = str(item.get("content") or "").strip()
    if not title:
        title = (summary[:80] if summary else content[:80]).strip() or "KG Event"
    if not summary:
        summary = (content[:240] if content else title).strip() or title
    if not content:
        content = summary or title

    references = dict(item.get("references") if isinstance(item.get("references"), dict) else {})
    for key in (
        "source",
        "source_file",
        "source_path",
        "chunk_index",
        "content_hash",
        "content_len",
        "pipeline_hash",
        "active_pipeline_hash",
    ):
        value = meta.get(key)
        if value is not None and key not in references:
            references[key] = value
    references.setdefault("kg_python_plugin", plugin_ref)

    extra_data = dict(item.get("extra_data") if isinstance(item.get("extra_data"), dict) else {})
    extra_data.setdefault("kg_python_plugin", plugin_ref)

    raw_entities = item.get("entities") if isinstance(item.get("entities"), list) else []
    entities: list[EventEntityInput] = []
    for entity_index, raw_entity in enumerate(raw_entities):
        entity = _coerce_event_entity(raw_entity, event_index=index, entity_index=entity_index)
        if entity is not None:
            entities.append(entity)

    doc_id = _coerce_uuid(item.get("document_id")) or _coerce_uuid(meta.get("document_id")) or _coerce_uuid(meta.get("doc_id"))
    chunk_id = _coerce_uuid(item.get("chunk_id")) or _coerce_uuid(meta.get("chunk_id")) or _coerce_uuid(meta.get("id"))
    if chunk_id is None and source_doc is not None:
        chunk_id = _coerce_uuid(getattr(source_doc, "id", None))

    return IndexRecord(
        kind=IndexKind.EVENT,
        title=title,
        summary=summary,
        content=content,
        metadata=dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        document_id=doc_id,
        chunk_id=chunk_id,
        references=references,
        extra_data=extra_data,
        vector=_coerce_vector(item.get("vector")),
        entities=entities,
    )


def _coerce_kg_events(result: Any, *, documents: list[Document], plugin_ref: str) -> list[IndexRecord]:
    events: list[IndexRecord] = []
    for idx, item in enumerate(_iter_kg_result(result)):
        event = _coerce_kg_event(item, documents=documents, plugin_ref=plugin_ref, index=idx)
        if event is not None:
            try:
                validate_no_reserved_platform_metadata_views(event.metadata, field_label="kg plugin metadata")
            except PipelinePluginContractError as exc:
                raise PythonPipelinePluginError(str(exc)) from exc
            events.append(event)
    return events


def apply_governance_python_plugin(
    documents: list[Document],
    *,
    plugin_ref: str,
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    ctx = {"stage": "governance", **dict(context or {})}
    _ensure_registered_plugin_stage(plugin_ref, expected_stage="governance")
    func = _load_plugin_callable(
        plugin_ref,
        default_function=_DEFAULT_GOVERNANCE_FUNC,
        directories=_context_plugin_directories(ctx),
        require_test_report=_context_require_test_report(ctx),
    )
    input_documents = strip_reserved_platform_metadata_views(list(documents or []))
    result = _invoke_plugin(func, documents=input_documents, params=dict(params or {}), context=ctx)
    output = _coerce_documents(result, stage="governance", plugin_ref=plugin_ref)
    return _apply_registered_plugin_contracts(output, plugin_ref=plugin_ref, stage="governance", context=ctx)


def apply_chunk_python_plugin(
    documents: list[Document],
    *,
    plugin_ref: str,
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    ctx = {"stage": "chunking", **dict(context or {})}
    _ensure_registered_plugin_stage(plugin_ref, expected_stage="chunk")
    func = _load_plugin_callable(
        plugin_ref,
        default_function=_DEFAULT_CHUNKING_FUNC,
        directories=_context_plugin_directories(ctx),
        require_test_report=_context_require_test_report(ctx),
    )
    input_documents = strip_reserved_platform_metadata_views(list(documents or []))
    result = _invoke_plugin(func, documents=input_documents, params=dict(params or {}), context=ctx)
    chunks = _coerce_documents(result, stage="chunk", plugin_ref=plugin_ref)
    for idx, chunk in enumerate(chunks):
        meta = dict(chunk.metadata or {})
        meta.setdefault("chunk_strategy", "python_plugin")
        meta.setdefault("chunk_python_plugin", plugin_ref)
        meta.setdefault("chunk_index", idx)
        chunk.metadata = meta
    return _apply_registered_plugin_contracts(chunks, plugin_ref=plugin_ref, stage="chunk", context=ctx)


def apply_kg_python_plugin(
    documents: list[Document],
    *,
    plugin_ref: str,
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[IndexRecord]:
    ctx = {"stage": "kg", **dict(context or {})}
    _ensure_registered_plugin_stage(plugin_ref, expected_stage="kg")
    func = _load_plugin_callable(
        plugin_ref,
        default_function=_DEFAULT_KG_FUNC,
        directories=_context_plugin_directories(ctx),
        require_test_report=_context_require_test_report(ctx),
    )
    docs = strip_reserved_platform_metadata_views(list(documents or []))
    result = _invoke_plugin(func, documents=docs, params=dict(params or {}), context=ctx)
    events = _coerce_kg_events(result, documents=docs, plugin_ref=plugin_ref)
    return _apply_registered_kg_plugin_contracts(events, plugin_ref=plugin_ref, context=ctx)


__all__ = [
    "PythonPipelinePluginError",
    "apply_chunk_python_plugin",
    "apply_governance_python_plugin",
    "apply_kg_python_plugin",
]
