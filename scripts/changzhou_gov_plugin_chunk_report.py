#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

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

from app.rag.pipeline_plugins.reports import build_pipeline_plugin_chunk_report  # noqa: E402

SCHEMA = "mimirq.changzhou_gov_service_knowledge.chunk_report.v1"
DEFAULT_PLUGIN_DIR = "plugins/pipelines/changzhou-gov-service-knowledge"
DEFAULT_SAMPLE = "plugins/pipelines/changzhou-gov-service-knowledge/sample.json"
DEFAULT_JSON_OUT = "/tmp/changzhou_gov_plugin_chunk_report.json"
DEFAULT_MARKDOWN_OUT = "/tmp/changzhou_gov_plugin_chunk_report.md"
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
_TITLE_METADATA_KEYS = (
    "service_name",
    "case_title",
    "question",
    "source_topic",
    "category_leaf",
    "source_sheet",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_one_line(value: Any, *, limit: int = 160) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def build_chunk_report(
    plugin_dir: str | Path = DEFAULT_PLUGIN_DIR,
    *,
    input_path: str | Path = DEFAULT_SAMPLE,
    max_examples_per_section: int = 2,
    preview_chars: int = 180,
    chunk_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = build_pipeline_plugin_chunk_report(
        plugin_dir,
        input_path=input_path,
        schema=SCHEMA,
        max_examples_per_section=max_examples_per_section,
        preview_chars=preview_chars,
        chunk_params=chunk_params,
        section_metadata_keys=("knowledge_section",),
        title_metadata_keys=_TITLE_METADATA_KEYS,
        metadata_highlight_keys=_METADATA_HIGHLIGHT_KEYS,
        record_type_metadata_key="gov_knowledge_type",
        extra_example_metadata_fields={
            "gov_knowledge_type": "gov_knowledge_type",
            "section_type": "section_type",
        },
    )
    for section in report.get("sections") or []:
        if isinstance(section, dict) and "record_type_counts" in section:
            section["gov_knowledge_types"] = section.pop("record_type_counts")
    return report


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
