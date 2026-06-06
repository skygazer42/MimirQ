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


def _selector_text(value: Any) -> str:
    if not _is_selector(value):
        return ""
    return f"{value[0]}.{value[1]}"


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


def _node_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_text(node.get("id")): node for node in nodes if _text(node.get("id"))}


def _condition_values_for_selector(cases: list[Any], selector: str) -> list[str]:
    values: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        for condition in case.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if _selector_text(condition.get("variable_selector")) != selector:
                continue
            value = _text(condition.get("value"))
            if value and value not in values:
                values.append(value)
    return values


def _area_route_warnings(nodes: list[dict[str, Any]], start_variables: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    expected_selector = ""
    for selector, variable in start_variables.items():
        if _text(variable.get("variable")) == "areaName":
            expected_selector = selector
            break
    if not expected_selector:
        return []

    nodes_by_id = _node_by_id(nodes)
    warnings: list[dict[str, Any]] = []
    for node in nodes:
        data = _node_data(node)
        if data.get("type") != "if-else" or "区域" not in _text(data.get("title")):
            continue
        cases = data.get("cases") if isinstance(data.get("cases"), list) else []
        selectors = sorted(
            {
                selector
                for case in cases
                if isinstance(case, dict)
                for condition in case.get("conditions") or []
                if isinstance(condition, dict)
                for selector in [_selector_text(condition.get("variable_selector"))]
                if selector
            }
        )
        for selector in selectors:
            if selector == expected_selector:
                continue
            source_node_id = selector.split(".", 1)[0]
            source_data = _node_data(nodes_by_id.get(source_node_id, {}))
            warnings.append(
                {
                    "routing_node_id": _text(node.get("id")),
                    "routing_node_title": _text(data.get("title")),
                    "selector": selector,
                    "expected_selector": expected_selector,
                    "source_node_id": source_node_id,
                    "source_node_title": _text(source_data.get("title")),
                    "source_node_type": _text(source_data.get("type")),
                    "condition_values": _condition_values_for_selector(cases, selector),
                    "recommendation": (
                        "Route regional knowledge from inputs.areaName directly, "
                        "or normalize it deterministically before the area branch."
                    ),
                }
            )
    return warnings


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


def _case_dify_inputs(case: dict[str, Any]) -> dict[str, Any]:
    raw = case.get("dify_inputs")
    if raw is None:
        raw = case.get("app_inputs")
    if not isinstance(raw, dict):
        return {}
    return {_text(key): value for key, value in raw.items() if _text(key)}


def _case_input_violations(
    cases: list[dict[str, Any]],
    hidden_required: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required_inputs = [
        {
            "variable": _text(item.get("variable")),
            "selector": _text(item.get("selector")),
        }
        for item in hidden_required
        if _text(item.get("variable")) and _text(item.get("selector"))
    ]
    violations: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        inputs = _case_dify_inputs(case)
        missing = [item for item in required_inputs if item["variable"] not in inputs or _text(inputs.get(item["variable"])) == ""]
        if not missing:
            continue
        case_id = _text(case.get("id") or case.get("case_id")) or f"case-{index + 1}"
        missing_inputs = [item["variable"] for item in missing]
        violations.append(
            {
                "id": case_id,
                "query": _text(case.get("query")),
                "missing_inputs": missing_inputs,
                "selectors": [item["selector"] for item in missing],
                "recommendation": f"Add dify_inputs.{missing_inputs[0]} for this case before calling the Dify App API.",
            }
        )
    return violations


def lint_workflow(workflow: dict[str, Any], *, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    nodes = _graph_nodes(workflow)
    start_variables = _start_variables(nodes)
    area_route_warnings = _area_route_warnings(nodes, start_variables)
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

    summary: dict[str, Any] = {
        "start_variables": len(start_variables),
        "referenced_start_variables": sum(1 for refs in references_by_selector.values() if refs),
        "hidden_required_start_variables": len(hidden_required),
    }
    report: dict[str, Any] = {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_workflow_lint.v1",
        "summary": summary,
        "hidden_required_start_variables": hidden_required,
    }
    if area_route_warnings:
        summary["area_route_warnings"] = len(area_route_warnings)
        report["area_route_warnings"] = area_route_warnings
    if cases is not None:
        case_violations = _case_input_violations(cases, hidden_required)
        summary["case_inputs_checked"] = len(cases)
        summary["case_input_violations"] = len(case_violations)
        report["case_input_violations"] = case_violations
    return report


def _load_workflow_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow JSON must be an object")
    return payload


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("cases file must be an object with cases[] or a cases[] list")
    return [item for item in cases if isinstance(item, dict)]


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
    parser.add_argument("--cases", default="")
    parser.add_argument(
        "--case-inputs-only",
        action="store_true",
        help="Exit non-zero only for case input violations; keep workflow warnings in the report.",
    )
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
        cases = _load_cases(str(args.cases)) if _text(args.cases) else None
        report = lint_workflow(workflow, cases=cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-workflow-lint] ERR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if bool(args.case_inputs_only):
        issue_count = int(summary.get("case_input_violations") or 0)
    else:
        issue_count = int(summary.get("hidden_required_start_variables") or 0) + int(
            summary.get("case_input_violations") or 0
        )
    return 0 if issue_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
