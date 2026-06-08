from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.rag.pipeline_plugins.contracts import RESERVED_PLATFORM_METADATA_VIEW_KEYS
from app.rag.pipeline_plugins.local_runner import load_plugin_test_input
from app.rag.pipeline_plugins.registry import describe_plugin_dir
from app.rag.pipeline_plugins.runtime import (
    apply_chunk_python_plugin,
    apply_governance_python_plugin,
    apply_kg_python_plugin,
)

PIPELINE_PLUGIN_CHUNK_REPORT_SCHEMA = "mimirq.pipeline_plugin_chunk_report.v1"
_RESERVED_VIEW_KEYS = set(RESERVED_PLATFORM_METADATA_VIEW_KEYS)
_DEFAULT_SECTION_METADATA_KEYS = ("knowledge_section", "section", "section_label", "source_group")
_DEFAULT_TITLE_METADATA_KEYS = (
    "title",
    "name",
    "record_label",
    "question",
    "category_leaf",
    "source_topic",
    "source_sheet",
)
_SOURCE_METADATA_KEYS = ("source", "source_file", "source_path", "filename", "file_name")

DocumentResolver = Callable[[Document], str]
EventResolver = Callable[[Any], str]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_one_line(value: Any, *, limit: int = 160) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _metadata_value(metadata: Mapping[str, Any], key: str) -> Any:
    current: Any = metadata
    for part in str(key or "").split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _source(metadata: Mapping[str, Any]) -> str:
    for key in _SOURCE_METADATA_KEYS:
        text = _text(metadata.get(key))
        if text:
            return text
    return ""


def _source_section(source: str) -> str:
    for part in Path(source).parts:
        if len(part) >= 2 and part[:2].isdigit():
            return part
    return ""


def _default_document_section(doc: Document, *, metadata_keys: Sequence[str]) -> str:
    metadata = dict(doc.metadata or {})
    for key in metadata_keys:
        value = _metadata_value(metadata, key)
        text = _text(value)
        if text:
            return text
    section = _source_section(_source(metadata))
    return section or "unclassified"


def _default_event_section(event: Any, *, metadata_keys: Sequence[str]) -> str:
    for container_name in ("extra_data", "metadata", "references"):
        container = getattr(event, container_name, None)
        if not isinstance(container, Mapping):
            continue
        for key in metadata_keys:
            text = _text(_metadata_value(container, key))
            if text:
                return text
    references = getattr(event, "references", None)
    if isinstance(references, Mapping):
        section = _source_section(_source(references))
        if section:
            return section
    return "unclassified"


def _default_title(doc: Document, *, metadata_keys: Sequence[str]) -> str:
    metadata = dict(doc.metadata or {})
    for key in metadata_keys:
        value = _metadata_value(metadata, key)
        if isinstance(value, list):
            value = " / ".join(_text(item) for item in value if _text(item))
        text = _text(value)
        if text:
            return _clean_one_line(text, limit=100)
    first_line = next((line.strip() for line in _text(doc.page_content).splitlines() if line.strip()), "")
    return _clean_one_line(first_line, limit=100)


def _metadata_fields(documents: Sequence[Document]) -> list[str]:
    fields: set[str] = set()
    for doc in documents:
        for key in dict(doc.metadata or {}):
            if key in _RESERVED_VIEW_KEYS or key.startswith("_"):
                continue
            fields.add(str(key))
    return sorted(fields)


def _metadata_focus(metadata: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key in _RESERVED_VIEW_KEYS or key.startswith("_"):
            continue
        value = _metadata_value(metadata, key)
        if isinstance(value, str) and value.strip():
            out[key] = _clean_one_line(value, limit=120)
        elif isinstance(value, list):
            values = [_clean_one_line(item, limit=80) for item in value if _text(item)]
            if values:
                out[key] = values[:8]
        elif value is not None and not isinstance(value, (dict, set, tuple)):
            text = _text(value)
            if text:
                out[key] = _clean_one_line(text, limit=120)
    return out


def _chunk_example(
    doc: Document,
    *,
    preview_chars: int,
    title_resolver: DocumentResolver,
    metadata_highlight_keys: Sequence[str],
    extra_example_metadata_fields: Mapping[str, str],
) -> dict[str, Any]:
    metadata = dict(doc.metadata or {})
    example: dict[str, Any] = {
        "title": title_resolver(doc),
        "chunk_kind": _text(metadata.get("chunk_kind")) or "unknown",
        "content_chars": len(doc.page_content or ""),
        "metadata_focus": _metadata_focus(metadata, metadata_highlight_keys),
        "content_preview": _clean_one_line(doc.page_content, limit=max(40, int(preview_chars or 0))),
    }
    for output_key, metadata_key in extra_example_metadata_fields.items():
        if not output_key or metadata_key in _RESERVED_VIEW_KEYS or str(metadata_key).startswith("_"):
            continue
        example[str(output_key)] = _metadata_value(metadata, metadata_key)
    return example


def _entity_types(events: Sequence[Any]) -> list[str]:
    types: set[str] = set()
    for event in events:
        entities = getattr(event, "entities", None)
        if not isinstance(entities, list):
            continue
        for entity in entities:
            value = _text(getattr(entity, "type", ""))
            if value:
                types.add(value)
    return sorted(types)


def _as_count_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def build_pipeline_plugin_chunk_report(
    plugin_dir: str | Path,
    *,
    input_path: str | Path,
    schema: str = PIPELINE_PLUGIN_CHUNK_REPORT_SCHEMA,
    max_examples_per_section: int = 2,
    preview_chars: int = 180,
    governance_params: dict[str, Any] | None = None,
    chunk_params: dict[str, Any] | None = None,
    kg_params: dict[str, Any] | None = None,
    section_metadata_keys: Sequence[str] = _DEFAULT_SECTION_METADATA_KEYS,
    title_metadata_keys: Sequence[str] = _DEFAULT_TITLE_METADATA_KEYS,
    metadata_highlight_keys: Sequence[str] = (),
    section_resolver: DocumentResolver | None = None,
    event_section_resolver: EventResolver | None = None,
    title_resolver: DocumentResolver | None = None,
    record_type_metadata_key: str | None = None,
    extra_example_metadata_fields: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    plugin_path = Path(plugin_dir)
    sample_path = Path(input_path)
    descriptor = describe_plugin_dir(plugin_path, require_test_report=False)
    input_documents = load_plugin_test_input(sample_path)
    context = {"plugin_directories": [plugin_path], "require_test_report": False}
    governed = apply_governance_python_plugin(
        input_documents,
        plugin_ref=descriptor.refs["governance"],
        params=dict(governance_params or {}),
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        governed,
        plugin_ref=descriptor.refs["chunk"],
        params=dict(chunk_params or {}),
        context=context,
    )
    events = []
    if "kg" in descriptor.refs:
        events = apply_kg_python_plugin(
            chunks,
            plugin_ref=descriptor.refs["kg"],
            params=dict(kg_params or {}),
            context=context,
        )

    section_keys = tuple(section_metadata_keys or _DEFAULT_SECTION_METADATA_KEYS)
    resolve_section = section_resolver or (lambda doc: _default_document_section(doc, metadata_keys=section_keys))
    resolve_event_section = event_section_resolver or (
        lambda event: _default_event_section(event, metadata_keys=section_keys)
    )
    resolve_title = title_resolver or (
        lambda doc: _default_title(doc, metadata_keys=tuple(title_metadata_keys or _DEFAULT_TITLE_METADATA_KEYS))
    )

    records_by_section: dict[str, list[Document]] = defaultdict(list)
    chunks_by_section: dict[str, list[Document]] = defaultdict(list)
    events_by_section: dict[str, list[Any]] = defaultdict(list)
    for doc in governed:
        records_by_section[resolve_section(doc)].append(doc)
    for doc in chunks:
        chunks_by_section[resolve_section(doc)].append(doc)
    for event in events:
        events_by_section[resolve_event_section(event)].append(event)

    section_names = sorted(set(records_by_section) | set(chunks_by_section) | set(events_by_section))
    sections: list[dict[str, Any]] = []
    for section in section_names:
        section_records = records_by_section.get(section, [])
        section_chunks = chunks_by_section.get(section, [])
        section_events = events_by_section.get(section, [])
        chunk_kinds = Counter(_text(doc.metadata.get("chunk_kind")) or "unknown" for doc in section_chunks)
        section_report: dict[str, Any] = {
            "knowledge_section": section,
            "governed_records": len(section_records),
            "chunks": len(section_chunks),
            "kg_events": len(section_events),
            "chunk_kinds": _as_count_dict(chunk_kinds),
            "metadata_fields": _metadata_fields([*section_records, *section_chunks]),
            "kg_entity_types": _entity_types(section_events),
            "examples": [
                _chunk_example(
                    doc,
                    preview_chars=preview_chars,
                    title_resolver=resolve_title,
                    metadata_highlight_keys=tuple(metadata_highlight_keys or ()),
                    extra_example_metadata_fields=dict(extra_example_metadata_fields or {}),
                )
                for doc in section_chunks[: max(0, int(max_examples_per_section or 0))]
            ],
        }
        if record_type_metadata_key:
            record_types = Counter(
                _text(_metadata_value(doc.metadata or {}, record_type_metadata_key)) or "unknown" for doc in section_records
            )
            section_report["record_type_counts"] = _as_count_dict(record_types)
        sections.append(section_report)

    return {
        "schema": schema,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "plugin": {
            "id": descriptor.id,
            "version": descriptor.version,
            "package_hash": descriptor.package_hash,
            "dir": str(plugin_path),
            "input": str(sample_path),
        },
        "summary": {
            "input_documents": len(input_documents),
            "governed_records": len(governed),
            "chunks": len(chunks),
            "kg_events": len(events),
            "sections": len(sections),
        },
        "sections": sections,
    }


__all__ = ["PIPELINE_PLUGIN_CHUNK_REPORT_SCHEMA", "build_pipeline_plugin_chunk_report"]
