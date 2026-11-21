import importlib
import inspect
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from math import isfinite
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.rag.embedding.utils import validate_embedding_vectors
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
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


def _context_require_test_report(context: dict[str, Any] | None) -> bool | None:
    if not context:
        return None
    raw = context.get("require_test_report")
    if raw is not None:
        if not isinstance(raw, bool):
            raise PythonPipelinePluginError("require_test_report must be a boolean or null")
        return raw
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
    if not validation["ok"]:
        first = validation["errors"][0]
        raise PythonPipelinePluginError(f"plugin metadata contract failed for {first['field']}: {first['reason']}")
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
    if not validation["ok"]:
        first = validation["errors"][0]
        raise PythonPipelinePluginError(f"plugin KG metadata contract failed for {first['field']}: {first['reason']}")
    return events


def _invoke_plugin(
    func: Callable[..., Any],
    *,
    documents: list[Document],
    params: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
        raise PythonPipelinePluginError("python pipeline plugins must be synchronous callables")
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        result = func(documents, params, context)
    else:
        positional, kwargs = _plugin_call_arguments(
            sig,
            documents=documents,
            params=params,
            context=context,
        )
        result = func(*positional, **kwargs)
    if inspect.isawaitable(result) or inspect.isasyncgen(result):
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        raise PythonPipelinePluginError("python pipeline plugins must return synchronous results")
    return result


def _plugin_call_arguments(
    signature: inspect.Signature,
    *,
    documents: list[Document],
    params: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    named_values = {
        "documents": documents,
        "items": documents,
        "docs": documents,
        "params": params,
        "context": context,
    }
    for name in ("chunk_size", "chunk_overlap", "stage"):
        if name in context:
            named_values[name] = context[name]
    kwargs: dict[str, Any] = {}
    positional: list[Any] = []
    for index, (name, param) in enumerate(signature.parameters.items()):
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            if name in named_values:
                positional.append(named_values[name])
            elif param.default is not inspect.Parameter.empty:
                positional.append(param.default)
            elif index == 0:
                positional.append(documents)
            else:
                break
        elif name in named_values and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            kwargs[name] = named_values[name]
        elif (
            index == 0
            and param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
            and param.default is inspect.Parameter.empty
        ):
            positional.append(documents)
    return positional, kwargs


def _coerce_metadata(value: Any, *, field_name: str = "metadata") -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PythonPipelinePluginError(f"python plugin {field_name} must be an object or null")
    return dict(value)


def _coerce_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float, bool)):
        raise PythonPipelinePluginError(f"python plugin {field_name} must be scalar text or null")
    if isinstance(value, float) and not isfinite(value):
        raise PythonPipelinePluginError(f"python plugin {field_name} must be finite")
    return str(value)


def _coerce_document(item: Any, *, stage: str, plugin_ref: str, index: int) -> Document:
    if isinstance(item, Document):
        meta = dict(item.metadata or {})
        meta[f"{stage}_python_plugin"] = plugin_ref
        return Document(page_content=item.page_content, metadata=meta, id=getattr(item, "id", None))

    if isinstance(item, str):
        return Document(page_content=item, metadata={f"{stage}_python_plugin": plugin_ref})

    if isinstance(item, dict):
        content = item.get("page_content")
        if content is None:
            content = item.get("content")
        if content is None:
            content = item.get("text")
        if content is None:
            raise PythonPipelinePluginError(
                f"python plugin document at index {index} must provide page_content, content or text"
            )
        meta = _coerce_metadata(item.get("metadata"))
        meta[f"{stage}_python_plugin"] = plugin_ref
        doc_id = item.get("id")
        return Document(page_content=_coerce_text(content, field_name="document content"), metadata=meta, id=doc_id)

    raise PythonPipelinePluginError(f"python plugin returned unsupported item at index {index}: {type(item).__name__}")


@contextmanager
def _result_iterator(result: Iterable[Any]) -> Iterator[Iterator[Any]]:
    iterator = iter(result)
    try:
        yield iterator
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()


def _coerce_documents(result: Any, *, stage: str, plugin_ref: str) -> list[Document]:
    if result is None:
        raise PythonPipelinePluginError("python plugin must return documents; use an empty list for no output")
    if isinstance(result, bytes):
        result = result.decode("utf-8")
    if isinstance(result, (Document, dict, str)):
        result = [result]
    if not isinstance(result, Iterable):
        raise PythonPipelinePluginError(f"python plugin returned unsupported result: {type(result).__name__}")

    out: list[Document] = []
    with _result_iterator(result) as iterator:
        for idx, item in enumerate(iterator):
            doc = _coerce_document(item, stage=stage, plugin_ref=plugin_ref, index=idx)
            if doc.page_content.strip():
                out.append(doc)
    return out


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _coerce_vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise PythonPipelinePluginError("python plugin vector must be a list or null")
    if not value:
        return None
    out: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise PythonPipelinePluginError("python plugin vector values must be finite numbers")
        try:
            out.append(float(item))
        except (OverflowError, TypeError, ValueError) as exc:
            raise PythonPipelinePluginError("python plugin vector values must be finite numbers") from exc
    try:
        return validate_embedding_vectors([out], count=1)[0]
    except ValueError as exc:
        raise PythonPipelinePluginError("python plugin vector values must be finite numbers") from exc


def _coerce_event_entity(item: Any, *, event_index: int, entity_index: int) -> EventEntityInput | None:
    if not isinstance(item, dict):
        raise PythonPipelinePluginError(
            f"kg plugin returned unsupported entity at event {event_index}, index {entity_index}: {type(item).__name__}"
        )
    raw_name = item.get("name")
    name = _coerce_text(raw_name, field_name="entity name")
    name = name.strip() if name is not None else None
    if not name:
        return None
    raw_normalized = item.get("normalized_name")
    if raw_normalized is None:
        raw_normalized = item.get("normalized")
    normalized = _coerce_text(raw_normalized, field_name="entity normalized_name")
    normalized = normalized.strip() if normalized is not None else ""
    ent_type = _coerce_text(item.get("type"), field_name="entity type")
    ent_type = ent_type.strip() if ent_type is not None else ""
    optional_text: dict[str, str | None] = {}
    for key in ("description", "role", "evidence_quote", "evidence_source"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise PythonPipelinePluginError(
                f"kg plugin entity {key} must be a string or null at event {event_index}, index {entity_index}"
            )
        optional_text[key] = value.strip() if value is not None else None
    coordinates: dict[str, int | None] = {}
    for key in ("evidence_start_char", "evidence_end_char"):
        raw = item.get(key)
        coordinate = _coerce_int(raw)
        if raw is not None and (coordinate is None or coordinate < 0):
            raise PythonPipelinePluginError(f"kg plugin entity {key} must be a nonnegative integer")
        coordinates[key] = coordinate
    return EventEntityInput(
        name=name,
        normalized_name=normalized or name,
        type=ent_type or "unknown",
        description=optional_text["description"],
        vector=_coerce_vector(item.get("vector")),
        role=optional_text["role"],
        evidence_quote=optional_text["evidence_quote"],
        evidence_source=optional_text["evidence_source"],
        evidence_start_char=coordinates["evidence_start_char"],
        evidence_end_char=coordinates["evidence_end_char"],
    )


def _source_document(documents: list[Document], index: int) -> Document | None:
    if not documents:
        return None
    if not 0 <= index < len(documents):
        raise PythonPipelinePluginError("kg plugin source_index is outside the source document batch")
    return documents[index]


def _iter_kg_result(result: Any) -> list[Any]:
    if result is None:
        raise PythonPipelinePluginError("kg plugin must return events; use an empty list for no output")
    if isinstance(result, (dict, IndexRecord)):
        return [result]
    if isinstance(result, (str, bytes)):
        raise PythonPipelinePluginError("kg plugin must return event objects, not raw text")
    if not isinstance(result, Iterable):
        raise PythonPipelinePluginError(f"kg plugin returned unsupported result: {type(result).__name__}")
    with _result_iterator(result) as iterator:
        return list(iterator)


def _kg_event_text_fields(item: dict[str, Any]) -> tuple[str, str, str]:
    raw_title, raw_summary, raw_content = item.get("title"), item.get("summary"), item.get("content")
    title = _coerce_text(raw_title, field_name="event title")
    summary = _coerce_text(raw_summary, field_name="event summary")
    content = _coerce_text(raw_content, field_name="event content")
    title = title.strip() if title is not None else ""
    summary = summary.strip() if summary is not None else ""
    content = content.strip() if content is not None else ""
    if not (title or summary or content):
        raise PythonPipelinePluginError("kg plugin event must provide title, summary, or content")
    if not title:
        title = (summary or content)[:80].strip()
    if not summary:
        summary = (content or title)[:240].strip()
    return title, summary, content or summary


def _kg_event_references(
    item: dict[str, Any],
    *,
    source_metadata: dict[str, Any],
    plugin_ref: str,
) -> dict[str, Any]:
    references = _coerce_metadata(item.get("references"), field_name="references")
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
        value = source_metadata.get(key)
        if value is not None:
            if key in {"source", "source_file", "source_path"}:
                references.setdefault(key, value)
            else:
                references[key] = value
    references["kg_python_plugin"] = plugin_ref
    return references


def _kg_event_entities(item: dict[str, Any], *, event_index: int) -> list[EventEntityInput]:
    raw_entities = item.get("entities")
    if raw_entities is None:
        return []
    if not isinstance(raw_entities, list):
        raise PythonPipelinePluginError(f"kg plugin entities must be a list at event {event_index}")
    entities: list[EventEntityInput] = []
    for entity_index, raw_entity in enumerate(raw_entities):
        entity = _coerce_event_entity(
            raw_entity,
            event_index=event_index,
            entity_index=entity_index,
        )
        if entity is not None:
            entities.append(entity)
    return entities


def _kg_event_scope_ids(
    item: dict[str, Any],
    *,
    source_metadata: dict[str, Any],
    source_document: Document | None,
) -> tuple[UUID | None, UUID | None]:
    source_ids = {
        "document_id": _coerce_uuid(source_metadata.get("document_id")),
        "chunk_id": _coerce_uuid(source_metadata.get("chunk_id")),
    }
    for key, value in source_ids.items():
        if source_metadata.get(key) is not None and value is None:
            raise PythonPipelinePluginError(f"kg plugin source {key} must be a UUID")
    if source_ids["document_id"] is None:
        source_ids["document_id"] = _coerce_uuid(source_metadata.get("doc_id"))
    if source_ids["chunk_id"] is None:
        source_ids["chunk_id"] = _coerce_uuid(source_metadata.get("id"))
    if source_ids["chunk_id"] is None and source_document is not None:
        source_ids["chunk_id"] = _coerce_uuid(source_document.id)
    for key in ("document_id", "chunk_id"):
        raw = item.get(key)
        supplied = _coerce_uuid(raw)
        if raw is not None and supplied is None:
            raise PythonPipelinePluginError(f"kg plugin event {key} must be a UUID")
        canonical = source_ids[key]
        if canonical is not None and supplied is not None and canonical != supplied:
            raise PythonPipelinePluginError(f"kg plugin event {key} does not match its source document")
        if canonical is None:
            source_ids[key] = supplied
    return source_ids["document_id"], source_ids["chunk_id"]


def _kg_event_source_index(item: dict[str, Any], *, documents: list[Document], index: int) -> int:
    raw_index = item.get("source_index")
    if raw_index is not None:
        source_index = _coerce_int(raw_index)
        if source_index is None or source_index < 0:
            raise PythonPipelinePluginError("kg plugin source_index must be a nonnegative integer")
        return source_index
    if len(documents) == 1:
        return 0
    requested_chunk = _coerce_uuid(item.get("chunk_id"))
    if requested_chunk is not None:
        sources = [
            _kg_event_scope_ids({}, source_metadata=dict(document.metadata), source_document=document)[1]
            for document in documents
        ]
        matches = [position for position, chunk_id in enumerate(sources) if chunk_id == requested_chunk]
        if len(matches) == 1:
            return matches[0]
        if any(chunk_id is not None for chunk_id in sources):
            raise PythonPipelinePluginError("kg plugin chunk_id does not identify exactly one source document")
    return index


def _coerce_kg_event(
    item: Any,
    *,
    documents: list[Document],
    plugin_ref: str,
    index: int,
) -> IndexRecord:
    if isinstance(item, IndexRecord):
        if item.kind != IndexKind.EVENT:
            raise PythonPipelinePluginError(f"kg plugin returned non-event IndexRecord at index {index}")
        scope = {"document_id": item.document_id, "chunk_id": item.chunk_id}
    elif isinstance(item, dict):
        scope = item
    else:
        raise PythonPipelinePluginError(f"kg plugin returned unsupported event at index {index}: {type(item).__name__}")

    source_index = _kg_event_source_index(scope, documents=documents, index=index)
    source_doc = _source_document(documents, source_index)
    meta = dict(source_doc.metadata) if source_doc is not None else {}
    document_id, chunk_id = _kg_event_scope_ids(
        scope,
        source_metadata=meta,
        source_document=source_doc,
    )
    if isinstance(item, IndexRecord):
        references = _kg_event_references({"references": item.references}, source_metadata=meta, plugin_ref=plugin_ref)
        extra_data = _coerce_metadata(item.extra_data, field_name="extra_data")
        extra_data["kg_python_plugin"] = plugin_ref
        return replace(item, document_id=document_id, chunk_id=chunk_id, references=references, extra_data=extra_data)

    title, summary, content = _kg_event_text_fields(item)
    references = _kg_event_references(
        item,
        source_metadata=meta,
        plugin_ref=plugin_ref,
    )
    extra_data = _coerce_metadata(item.get("extra_data"), field_name="extra_data")
    extra_data["kg_python_plugin"] = plugin_ref

    return IndexRecord(
        kind=IndexKind.EVENT,
        title=title,
        summary=summary,
        content=content,
        metadata=_coerce_metadata(item.get("metadata")),
        document_id=document_id,
        chunk_id=chunk_id,
        references=references,
        extra_data=extra_data,
        vector=_coerce_vector(item.get("vector")),
        entities=_kg_event_entities(item, event_index=index),
    )


def _coerce_kg_events(result: Any, *, documents: list[Document], plugin_ref: str) -> list[IndexRecord]:
    events: list[IndexRecord] = []
    for idx, item in enumerate(_iter_kg_result(result)):
        event = _coerce_kg_event(item, documents=documents, plugin_ref=plugin_ref, index=idx)
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
        chunk.metadata.setdefault("chunk_strategy", "python_plugin")
        chunk.metadata.setdefault("chunk_index", idx)
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
    events = _coerce_kg_events(result, documents=documents, plugin_ref=plugin_ref)
    if events and not documents:
        raise PythonPipelinePluginError("kg plugin events require source documents")
    return _apply_registered_kg_plugin_contracts(events, plugin_ref=plugin_ref, context=ctx)


__all__ = [
    "PythonPipelinePluginError",
    "apply_chunk_python_plugin",
    "apply_governance_python_plugin",
    "apply_kg_python_plugin",
]
