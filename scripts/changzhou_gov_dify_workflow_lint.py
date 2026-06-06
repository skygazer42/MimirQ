#!/usr/bin/env python3
"""Lint Dify workflow JSON for hidden required Start variables.

Dify can mark a Start variable as optional while later nodes still reference it
directly. In that shape the public App API may return a runtime 400 before the
request reaches MimirQ retrieval. This script keeps that boundary diagnosable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_dify_trace_report import (  # noqa: E402
    DEFAULT_CONSOLE_BASE_URL,
    DEFAULT_STORAGE_STATE,
    _request_json,
    load_console_token,
)

_TEMPLATE_REF_RE = re.compile(r"#([^#.\s]+)\.([^#\s]+)#")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_default(variable: dict[str, Any]) -> bool:
    for key in ("default", "default_value", "value"):
        if _text(variable.get(key)):
            return True
    return False


def _is_selector(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], str)
        and isinstance(value[1], str)
    )


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _graph_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    graph = workflow.get("graph")
    if not isinstance(graph, dict):
        return []
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def _start_variables(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    variables: dict[str, dict[str, Any]] = {}
    for node in nodes:
        data = _node_data(node)
        if data.get("type") != "start":
            continue
        start_node_id = _text(node.get("id"))
        if not start_node_id:
            continue
        for variable in data.get("variables") or []:
            if not isinstance(variable, dict):
                continue
            name = _text(variable.get("variable"))
            if not name:
                continue
            selector = f"{start_node_id}.{name}"
            variables[selector] = {
                "start_node_id": start_node_id,
                "variable": name,
                "selector": selector,
                "label": _text(variable.get("label")),
                "required": bool(variable.get("required")),
                "has_default": _has_default(variable),
            }
    return variables


def _iter_references(value: Any, *, path: str) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    if isinstance(value, str):
        for match in _TEMPLATE_REF_RE.finditer(value):
            references.append((f"{match.group(1)}.{match.group(2)}", path))
        return references
    if _is_selector(value):
        references.append((f"{value[0]}.{value[1]}", path))
        return references
    if isinstance(value, dict):
        for key, child in value.items():
            references.extend(_iter_references(child, path=f"{path}.{key}"))
        return references
    if isinstance(value, list):
        for index, child in enumerate(value):
            references.extend(_iter_references(child, path=f"{path}[{index}]"))
    return references


def lint_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    nodes = _graph_nodes(workflow)
    start_variables = _start_variables(nodes)
    references_by_selector: dict[str, list[dict[str, Any]]] = {selector: [] for selector in start_variables}

    for node_index, node in enumerate(nodes):
        data = _node_data(node)
        if data.get("type") == "start":
            continue
        node_id = _text(node.get("id"))
        context = {
            "node_id": node_id,
            "node_title": _text(data.get("title")),
            "node_type": _text(data.get("type")),
        }
        for selector, path in _iter_references(data, path=f"graph.nodes[{node_index}].data"):
            if selector not in references_by_selector:
                continue
            reference = {**context, "path": path}
            if reference not in references_by_selector[selector]:
                references_by_selector[selector].append(reference)

    hidden_required: list[dict[str, Any]] = []
    for selector, variable in start_variables.items():
        references = references_by_selector.get(selector) or []
        if not references:
            continue
        if variable["required"] or variable["has_default"]:
            continue
        hidden_required.append(
            {
                **variable,
                "reference_count": len(references),
                "references": references,
                "recommendation": (
                    f"Pass inputs.{variable['variable']} or add a Dify workflow "
                    "default/fallback before referencing this variable."
                ),
            }
        )

    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_workflow_lint.v1",
        "summary": {
            "start_variables": len(start_variables),
            "referenced_start_variables": sum(1 for refs in references_by_selector.values() if refs),
            "hidden_required_start_variables": len(hidden_required),
        },
        "hidden_required_start_variables": hidden_required,
    }


def _load_workflow_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow JSON must be an object")
    return payload


def _fetch_draft_workflow(
    *,
    app_id: str,
    console_base_url: str,
    console_token: str,
    timeout: float,
) -> dict[str, Any]:
    return _request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=f"/apps/{app_id}/workflows/draft",
        timeout=timeout,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint a Dify workflow for hidden required Start variables.")
    parser.add_argument("--workflow-json", default="")
    parser.add_argument("--app-id", default="")
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if _text(args.workflow_json):
            workflow = _load_workflow_json(str(args.workflow_json))
        else:
            app_id = _text(args.app_id)
            if not app_id:
                print("--app-id is required when --workflow-json is not provided", file=sys.stderr)
                return 2
            console_token = load_console_token(str(args.console_token), str(args.storage_state))
            if not console_token:
                print("DIFY_CONSOLE_TOKEN, --console-token, or --storage-state with console_token is required", file=sys.stderr)
                return 2
            workflow = _fetch_draft_workflow(
                app_id=app_id,
                console_base_url=str(args.console_base_url),
                console_token=console_token,
                timeout=float(args.timeout),
            )
        report = lint_workflow(workflow)
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-workflow-lint] ERR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if int((report.get("summary") or {}).get("hidden_required_start_variables") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
