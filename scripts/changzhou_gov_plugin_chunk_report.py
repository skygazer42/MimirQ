#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# This is a local review/report tool. Keep production config warnings in the
# service path, but avoid polluting handoff reports when SECRET_KEY is unset.
warnings.filterwarnings(
    "ignore",
    message=r"SECRET_KEY is not configured\..*",
    category=UserWarning,
)

from app.rag.pipeline_plugins.local_runner import load_plugin_test_input  # noqa: E402
from app.rag.pipeline_plugins.registry import describe_plugin_dir  # noqa: E402
from app.rag.pipeline_plugins.runtime import (  # noqa: E402
    apply_chunk_python_plugin,
    apply_governance_python_plugin,
    apply_kg_python_plugin,
)

SCHEMA = "mimirq.changzhou_gov_service_knowledge.chunk_report.v1"
DEFAULT_PLUGIN_DIR = "plugins/pipelines/changzhou-gov-service-knowledge"
DEFAULT_SAMPLE = "plugins/pipelines/changzhou-gov-service-knowledge/sample.json"
DEFAULT_JSON_OUT = "/tmp/changzhou_gov_plugin_chunk_report.json"
DEFAULT_MARKDOWN_OUT = "/tmp/changzhou_gov_plugin_chunk_report.md"
_RESERVED_VIEW_KEYS = {
    "_indexed_metadata",
    "_display_metadata",
    "_evaluable_metadata",
    "_record_identity",
    "_retrieval_text",
    "_retrieval_display_content",
}
_METADATA_HIGHLIGHT_KEYS = (
    "gov_knowledge_type",
    "district",
    "service_name",
    "case_title",
    "section_type",
    "question",
    "source_topic",
    "source_sheet",
    "source_department",
    "category_path",
    "applicable_area",
    "service_url",
    "urls",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_one_line(value: Any, *, limit: int = 160) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _source(value: dict[str, Any]) -> str:
    for key in ("source", "source_file", "source_path", "filename", "file_name"):
        text = _text(value.get(key))
        if text:
            return text
    return ""


def _section(doc: Document) -> str:
    meta = dict(doc.metadata or {})
    section = _text(meta.get("knowledge_section"))
    if section:
        return section
    source = _source(meta)
    for part in Path(source).parts:
        if len(part) >= 2 and part[:2].isdigit():
            return part
    return "未识别"


def _title(doc: Document) -> str:
    meta = dict(doc.metadata or {})
    for key in ("service_name", "case_title", "question", "source_topic", "category_leaf", "source_sheet"):
        value = meta.get(key)
        if isinstance(value, list):
            value = " / ".join(_text(item) for item in value if _text(item))
        text = _text(value)
        if text:
            return _clean_one_line(text, limit=100)
    first_line = next((line.strip() for line in _text(doc.page_content).splitlines() if line.strip()), "")
    return _clean_one_line(first_line, limit=100)


def _metadata_fields(documents: list[Document]) -> list[str]:
    fields: set[str] = set()
    for doc in documents:
        for key in dict(doc.metadata or {}):
            if key in _RESERVED_VIEW_KEYS or key.startswith("_"):
                continue
            fields.add(str(key))
    return sorted(fields)


def _metadata_focus(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _METADATA_HIGHLIGHT_KEYS:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = _clean_one_line(value, limit=120)
        elif isinstance(value, list):
            values = [_clean_one_line(item, limit=80) for item in value if _text(item)]
            if values:
                out[key] = values[:8]
    return out


def _chunk_example(doc: Document, *, preview_chars: int) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    return {
        "title": _title(doc),
        "chunk_kind": _text(meta.get("chunk_kind")) or "unknown",
        "gov_knowledge_type": _text(meta.get("gov_knowledge_type")),
        "section_type": _text(meta.get("section_type")),
        "content_chars": len(doc.page_content or ""),
        "metadata_focus": _metadata_focus(meta),
        "content_preview": _clean_one_line(doc.page_content, limit=max(40, int(preview_chars or 0))),
    }


def _event_section(event: Any) -> str:
    extra = getattr(event, "extra_data", None)
    if isinstance(extra, dict):
        section = _text(extra.get("knowledge_section"))
        if section:
            return section
    references = getattr(event, "references", None)
    if isinstance(references, dict):
        source = _text(references.get("source") or references.get("source_file") or references.get("source_path"))
        for part in Path(source).parts:
            if len(part) >= 2 and part[:2].isdigit():
                return part
    return "未识别"


def _entity_types(events: list[Any]) -> list[str]:
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


def build_chunk_report(
    plugin_dir: str | Path = DEFAULT_PLUGIN_DIR,
    *,
    input_path: str | Path = DEFAULT_SAMPLE,
    max_examples_per_section: int = 2,
    preview_chars: int = 180,
    chunk_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plugin_path = Path(plugin_dir)
    sample_path = Path(input_path)
    descriptor = describe_plugin_dir(plugin_path, require_test_report=False)
    input_documents = load_plugin_test_input(sample_path)
    context = {"plugin_directories": [plugin_path], "require_test_report": False}
    governed = apply_governance_python_plugin(
        input_documents,
        plugin_ref=descriptor.refs["governance"],
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        governed,
        plugin_ref=descriptor.refs["chunk"],
        params=dict(chunk_params or {}),
        context=context,
    )
    events = apply_kg_python_plugin(
        chunks,
        plugin_ref=descriptor.refs["kg"],
        context=context,
    )

    records_by_section: dict[str, list[Document]] = defaultdict(list)
    chunks_by_section: dict[str, list[Document]] = defaultdict(list)
    events_by_section: dict[str, list[Any]] = defaultdict(list)
    for doc in governed:
        records_by_section[_section(doc)].append(doc)
    for doc in chunks:
        chunks_by_section[_section(doc)].append(doc)
    for event in events:
        events_by_section[_event_section(event)].append(event)

    section_names = sorted(set(records_by_section) | set(chunks_by_section) | set(events_by_section))
    sections: list[dict[str, Any]] = []
    for section in section_names:
        section_records = records_by_section.get(section, [])
        section_chunks = chunks_by_section.get(section, [])
        section_events = events_by_section.get(section, [])
        chunk_kinds = Counter(_text(doc.metadata.get("chunk_kind")) or "unknown" for doc in section_chunks)
        gov_types = Counter(_text(doc.metadata.get("gov_knowledge_type")) or "unknown" for doc in section_records)
        sections.append(
            {
                "knowledge_section": section,
                "governed_records": len(section_records),
                "chunks": len(section_chunks),
                "kg_events": len(section_events),
                "gov_knowledge_types": _as_count_dict(gov_types),
                "chunk_kinds": _as_count_dict(chunk_kinds),
                "metadata_fields": _metadata_fields([*section_records, *section_chunks]),
                "kg_entity_types": _entity_types(section_events),
                "examples": [
                    _chunk_example(doc, preview_chars=preview_chars)
                    for doc in section_chunks[: max(0, int(max_examples_per_section or 0))]
                ],
            }
        )

    return {
        "schema": SCHEMA,
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


def _join_counts(values: dict[str, int]) -> str:
    if not values:
        return ""
    return ", ".join(f"`{key}`={value}" for key, value in values.items())


def _join_inline(values: list[str], *, limit: int = 8) -> str:
    return ", ".join(f"`{value}`" for value in values[:limit])


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_clean_one_line(cell, limit=900).replace("|", "\\|") for cell in row) + " |" for row in rows)
    return lines


def format_markdown_report(report: dict[str, Any]) -> str:
    plugin = report.get("plugin") if isinstance(report.get("plugin"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    sections = report.get("sections") if isinstance(report.get("sections"), list) else []
    lines = [
        "# Changzhou Gov Plugin Chunk Report",
        "",
        f"**Status:** {'PASSED' if report.get('passed') is True else 'FAILED'}",
        f"**Plugin:** {_text(plugin.get('id'))}@{_text(plugin.get('version'))}",
        f"**Generated at:** {_text(report.get('generated_at'))}",
        f"**Input:** `{_text(plugin.get('input'))}`",
        "",
        "## Summary",
        "",
        *_markdown_table(
            ["input_documents", "governed_records", "chunks", "kg_events", "sections"],
            [
                [
                    _text(summary.get("input_documents")),
                    _text(summary.get("governed_records")),
                    _text(summary.get("chunks")),
                    _text(summary.get("kg_events")),
                    _text(summary.get("sections")),
                ]
            ],
        ),
        "",
        "## Section Matrix",
        "",
        *_markdown_table(
            ["Section", "Records", "Chunks", "chunk_kinds", "metadata_fields", "kg_entity_types"],
            [
                [
                    _text(section.get("knowledge_section")),
                    _text(section.get("governed_records")),
                    _text(section.get("chunks")),
                    _join_counts(section.get("chunk_kinds") if isinstance(section.get("chunk_kinds"), dict) else {}),
                    _join_inline(section.get("metadata_fields") if isinstance(section.get("metadata_fields"), list) else {}),
                    _join_inline(section.get("kg_entity_types") if isinstance(section.get("kg_entity_types"), list) else {}),
                ]
                for section in sections
                if isinstance(section, dict)
            ],
        ),
        "",
        "## Chunk Examples",
    ]
    for section in sections:
        if not isinstance(section, dict):
            continue
        lines.extend(["", f"### {_text(section.get('knowledge_section'))}"])
        examples = section.get("examples") if isinstance(section.get("examples"), list) else []
        if not examples:
            lines.append("- No chunk examples emitted.")
            continue
        for example in examples:
            if not isinstance(example, dict):
                continue
            focus = example.get("metadata_focus") if isinstance(example.get("metadata_focus"), dict) else {}
            focus_text = "; ".join(f"{key}={_clean_one_line(value, limit=100)}" for key, value in focus.items())
            suffix = f" metadata: {focus_text}" if focus_text else ""
            lines.append(
                "- "
                f"`{_text(example.get('chunk_kind'))}` "
                f"{_text(example.get('title'))} "
                f"({example.get('content_chars')} chars). "
                f"{_text(example.get('content_preview'))}"
                f"{suffix}"
            )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This report is generated from the plugin sample and plugin contracts; it does not write to the database, vector store, or KG store.",
            "- Use it to review how 01-06 source families are governed, chunked, and represented for retrieval/KG before production ingestion.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a reviewable Changzhou plugin governance/chunk/KG report.")
    parser.add_argument("--plugin-dir", default=DEFAULT_PLUGIN_DIR)
    parser.add_argument("--input", default=DEFAULT_SAMPLE, dest="input_path")
    parser.add_argument("--json-out", default=DEFAULT_JSON_OUT, help="Write JSON report to this path, or '-' for stdout.")
    parser.add_argument("--markdown-out", default=DEFAULT_MARKDOWN_OUT, help="Write Markdown report to this path. Empty disables it.")
    parser.add_argument("--max-examples-per-section", type=int, default=2)
    parser.add_argument("--preview-chars", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_chunk_report(
        args.plugin_dir,
        input_path=args.input_path,
        max_examples_per_section=int(args.max_examples_per_section),
        preview_chars=int(args.preview_chars),
    )
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if str(args.json_out or "-") == "-":
        print(json_text, end="")
    else:
        _write_text(args.json_out, json_text)
    if _text(args.markdown_out):
        _write_text(args.markdown_out, format_markdown_report(report))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
