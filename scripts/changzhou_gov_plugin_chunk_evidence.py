#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.changzhou_gov.plugin_chunk_evidence.v1"
DEFAULT_INPUT = "/tmp/changzhou_gov_plugin_chunk_report.json"
DEFAULT_JSON_OUT = "/tmp/changzhou_gov_plugin_chunk_evidence.json"
DEFAULT_MARKDOWN_OUT = "/tmp/changzhou_gov_plugin_chunk_evidence.md"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if _text(item)] if isinstance(value, list) else []


def _section_evidence(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledge_section": _text(section.get("knowledge_section")),
        "governed_records": int(section.get("governed_records") or 0),
        "chunks": int(section.get("chunks") or 0),
        "kg_events": int(section.get("kg_events") or 0),
        "gov_knowledge_types": _dict_value(section.get("gov_knowledge_types")),
        "chunk_kinds": _dict_value(section.get("chunk_kinds")),
        "metadata_fields": _string_list(section.get("metadata_fields")),
        "kg_entity_types": _string_list(section.get("kg_entity_types")),
    }


def build_evidence(raw_report_path: str | Path = DEFAULT_INPUT) -> dict[str, Any]:
    report = _load_json(raw_report_path)
    sections = [_section_evidence(section) for section in report.get("sections", []) if isinstance(section, dict)]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report": str(raw_report_path),
        "passed": report.get("passed") is True,
        "plugin": {
            "id": _text(_dict_value(report.get("plugin")).get("id")),
            "version": _text(_dict_value(report.get("plugin")).get("version")),
            "package_hash": _text(_dict_value(report.get("plugin")).get("package_hash")),
        },
        "summary": _dict_value(report.get("summary")),
        "sections": sections,
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_text(cell).replace("\n", " ").replace("|", "\\|") for cell in row) + " |" for row in rows)
    return lines


def _count_line(values: dict[str, Any]) -> str:
    return "; ".join(f"{key}={value}" for key, value in sorted(values.items()) if isinstance(value, int | float))


def _join_inline(values: list[str], *, limit: int = 10) -> str:
    return ", ".join(f"`{value}`" for value in values[:limit])


def format_markdown(evidence: dict[str, Any]) -> str:
    summary = _dict_value(evidence.get("summary"))
    plugin = _dict_value(evidence.get("plugin"))
    sections = evidence.get("sections") if isinstance(evidence.get("sections"), list) else []
    lines = [
        "# Changzhou Gov Plugin Chunk Evidence",
        "",
        f"**Status:** {'PASSED' if evidence.get('passed') is True else 'FAILED'}",
        f"**Generated at:** {_text(evidence.get('generated_at'))}",
        f"**Plugin:** {_text(plugin.get('id'))}@{_text(plugin.get('version'))}",
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
            ["Section", "Records", "Chunks", "KG Events", "chunk_kinds", "metadata_fields", "kg_entity_types"],
            [
                [
                    _text(section.get("knowledge_section")),
                    _text(section.get("governed_records")),
                    _text(section.get("chunks")),
                    _text(section.get("kg_events")),
                    _count_line(_dict_value(section.get("chunk_kinds"))),
                    _join_inline(_string_list(section.get("metadata_fields"))),
                    _join_inline(_string_list(section.get("kg_entity_types"))),
                ]
                for section in sections
                if isinstance(section, dict)
            ],
        ),
        "",
        "## Safety",
        "",
        "This evidence file intentionally omits raw chunk examples, content previews, and focused metadata values.",
    ]
    return "\n".join(lines) + "\n"


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build shareable Changzhou plugin chunk evidence from a local raw report.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--json-out", default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", default=DEFAULT_MARKDOWN_OUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        evidence = build_evidence(args.input)
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-gov-plugin-chunk-evidence] ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if _text(args.json_out) == "-":
        print(json_text, end="")
    else:
        _write_text(args.json_out, json_text)
    if _text(args.markdown_out):
        _write_text(args.markdown_out, format_markdown(evidence))
    return 0 if evidence.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
