#!/usr/bin/env python3
"""Lint Dify workflow JSON for hidden required Start variables.

Dify can mark a Start variable as optional while later nodes still reference it
directly. In that shape the public App API may return a runtime 400 before the
request reaches MimirQ retrieval. This script keeps that boundary diagnosable.
"""

from __future__ import annotations

import argparse
import copy
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
_WHOLE_TEMPLATE_REF_RE = re.compile(r"\s*\{\{#([^#.\s]+)\.([^#\s]+)#\}\}\s*")
_PROMPT_TEMPLATE_FORBIDDEN_PHRASES = (
    "必须按顺序包含以下标题",
    "必须按以下格式输出常见问题",
    "知识库内容中有",
    "输出此部分内容",
    "暂无相关常见问题QA知识",
)
_PROMPT_TEMPLATE_REPLACEMENTS = (
    ("必须按顺序包含以下标题", "请按以下标题顺序组织答案"),
    ("必须按以下格式输出常见问题", "请按以下格式整理常见问题"),
    ("知识库内容中有一件事系统操作指引相关内容，输出此部分内容", "如检索结果包含一件事系统操作指引，请补充对应内容"),
    ("知识库内容中有常见问题QA知识相关内容，输出此部分内容", "如检索结果包含常见问题QA，请整理为常见问答"),
    ("知识库内容中有", "如检索结果包含"),
    ("输出此部分内容", "请整理为用户可读内容"),
    ("暂无相关常见问题QA知识", "如无相关常见问题，可省略常见问答部分"),
)


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


def _selector_from_template_ref(value: Any) -> list[str] | None:
    if not isinstance(value, str):
        return None
    match = _WHOLE_TEMPLATE_REF_RE.fullmatch(value)
    if not match:
        return None
    return [match.group(1), match.group(2)]


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


def patch_area_route_selectors(workflow: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a workflow copy with regional route conditions bound to Start.areaName."""
    patched_workflow = copy.deepcopy(workflow)
    original_nodes = _graph_nodes(workflow)
    start_variables = _start_variables(original_nodes)
    warnings = _area_route_warnings(original_nodes, start_variables)
    if not warnings:
        return patched_workflow, []

    selectors_by_route: dict[str, dict[str, str]] = {}
    for warning in warnings:
        routing_node_id = _text(warning.get("routing_node_id"))
        selector = _text(warning.get("selector"))
        expected_selector = _text(warning.get("expected_selector"))
        if not routing_node_id or not selector or not expected_selector:
            continue
        selectors_by_route.setdefault(routing_node_id, {})[selector] = expected_selector

    patches: list[dict[str, Any]] = []
    for node in _graph_nodes(patched_workflow):
        node_id = _text(node.get("id"))
        replacements = selectors_by_route.get(node_id)
        if not replacements:
            continue
        data = _node_data(node)
        cases = data.get("cases") if isinstance(data.get("cases"), list) else []
        patched_counts = {selector: 0 for selector in replacements}
        for case in cases:
            if not isinstance(case, dict):
                continue
            for condition in case.get("conditions") or []:
                if not isinstance(condition, dict):
                    continue
                selector = _selector_text(condition.get("variable_selector"))
                expected_selector = replacements.get(selector)
                if not expected_selector:
                    continue
                condition["variable_selector"] = expected_selector.split(".", 1)
                patched_counts[selector] += 1
        for selector, count in patched_counts.items():
            if count <= 0:
                continue
            patches.append(
                {
                    "routing_node_id": node_id,
                    "routing_node_title": _text(data.get("title")),
                    "from_selector": selector,
                    "to_selector": replacements[selector],
                    "conditions_patched": count,
                }
            )
    return patched_workflow, patches


def _prompt_template_texts(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    for node_index, node in enumerate(nodes):
        data = _node_data(node)
        prompt_template = data.get("prompt_template")
        if not isinstance(prompt_template, list):
            continue
        for prompt_index, prompt in enumerate(prompt_template):
            if not isinstance(prompt, dict):
                continue
            text = _text(prompt.get("text"))
            if not text:
                continue
            texts.append(
                {
                    "node_index": node_index,
                    "prompt_index": prompt_index,
                    "node_id": _text(node.get("id")),
                    "node_title": _text(data.get("title")),
                    "node_type": _text(data.get("type")),
                    "path": f"graph.nodes[{node_index}].data.prompt_template[{prompt_index}].text",
                    "text": text,
                }
            )
    return texts


def _forbidden_prompt_phrases(text: str) -> list[str]:
    return [phrase for phrase in _PROMPT_TEMPLATE_FORBIDDEN_PHRASES if phrase in text]


def _prompt_template_leak_warnings(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in _prompt_template_texts(nodes):
        forbidden = _forbidden_prompt_phrases(_text(item.get("text")))
        if not forbidden:
            continue
        warnings.append(
            {
                "node_id": item["node_id"],
                "node_title": item["node_title"],
                "node_type": item["node_type"],
                "path": item["path"],
                "forbidden_phrases": forbidden,
                "recommendation": (
                    "Rewrite the prompt as model instructions only; "
                    "do not include user-visible template-control phrases."
                ),
            }
        )
    return warnings


def _sanitize_prompt_template_text(text: str) -> str:
    cleaned = text
    for old, new in _PROMPT_TEMPLATE_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)
    return cleaned


def patch_prompt_template_leaks(workflow: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a workflow copy with prompt-template control phrases rewritten."""
    patched_workflow = copy.deepcopy(workflow)
    patches: list[dict[str, Any]] = []
    nodes = _graph_nodes(patched_workflow)
    for item in _prompt_template_texts(nodes):
        text = _text(item.get("text"))
        forbidden = _forbidden_prompt_phrases(text)
        if not forbidden:
            continue
        node_index = int(item["node_index"])
        prompt_index = int(item["prompt_index"])
        nodes[node_index]["data"]["prompt_template"][prompt_index]["text"] = _sanitize_prompt_template_text(text)
        patches.append(
            {
                "node_id": item["node_id"],
                "node_title": item["node_title"],
                "path": item["path"],
                "forbidden_phrases": forbidden,
            }
        )
    return patched_workflow, patches


def _http_json_body_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    body = data.get("body")
    if not isinstance(body, dict) or body.get("type") != "json":
        return []
    entries = body.get("data")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _http_json_template_warnings(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for node_index, node in enumerate(nodes):
        data = _node_data(node)
        if data.get("type") != "http-request":
            continue
        for entry_index, entry in enumerate(_http_json_body_entries(data)):
            value = entry.get("value")
            if not isinstance(value, str) or "{{#" not in value:
                continue
            if _selector_from_template_ref(value):
                continue
            stripped = value.strip()
            if not stripped.startswith(("{", "[")):
                continue
            selectors = sorted({selector for selector, _path in _iter_references(value, path="value")})
            warnings.append(
                {
                    "node_id": _text(node.get("id")),
                    "node_title": _text(data.get("title")),
                    "node_type": _text(data.get("type")),
                    "path": f"graph.nodes[{node_index}].data.body.data[{entry_index}].value",
                    "template_selectors": selectors,
                    "recommendation": (
                        "Build the HTTP JSON body in a Code node with json.dumps, then reference "
                        "that node's payload_json as the whole body value."
                    ),
                }
            )
    return warnings


def _retrieval_payload_code(
    *,
    app_id: str,
    knowledge_id: str,
    retrieval_setting: dict[str, Any],
    metadata_defaults: dict[str, Any],
) -> str:
    metadata_defaults_json = json.dumps(metadata_defaults, ensure_ascii=False, indent=4)
    retrieval_setting_json = json.dumps(retrieval_setting, ensure_ascii=False, indent=4)
    app_id_literal = json.dumps(app_id, ensure_ascii=False)
    knowledge_id_literal = json.dumps(knowledge_id, ensure_ascii=False)
    return (
        "import json\n"
        "from typing import Any\n\n"
        f"_APP_ID = {app_id_literal}\n"
        f"_KNOWLEDGE_ID = {knowledge_id_literal}\n"
        f"_RETRIEVAL_SETTING = {retrieval_setting_json}\n"
        f"_METADATA_DEFAULTS = {metadata_defaults_json}\n\n"
        "def _text(value: Any) -> str:\n"
        "    if value is None:\n"
        "        return \"\"\n"
        "    if isinstance(value, (dict, list)):\n"
        "        return json.dumps(value, ensure_ascii=False)\n"
        "    return str(value)\n\n"
        "def _with_default(value: Any, default: Any = \"\") -> str:\n"
        "    text = _text(value).strip()\n"
        "    return text if text else _text(default).strip()\n\n"
        "def main(query=None, area_name=None, normalized_area=None, polished_query=None) -> dict:\n"
        "    query_text = _with_default(query, _METADATA_DEFAULTS.get(\"query\"))\n"
        "    metadata = {\n"
        "        \"app_id\": _APP_ID,\n"
        "        \"workflow_source\": _METADATA_DEFAULTS.get(\"workflow_source\", \"dify-http-rag-retrieval\"),\n"
        "        \"areaName\": _with_default(area_name, _METADATA_DEFAULTS.get(\"areaName\")),\n"
        "        \"normalized_area\": _with_default(normalized_area, _METADATA_DEFAULTS.get(\"normalized_area\")),\n"
        "        \"polished_query\": _with_default(polished_query, _METADATA_DEFAULTS.get(\"polished_query\") or query_text),\n"
        "    }\n"
        "    payload = {\n"
        "        \"knowledge_id\": _KNOWLEDGE_ID,\n"
        "        \"query\": query_text,\n"
        "        \"retrieval_setting\": _RETRIEVAL_SETTING,\n"
        "        \"metadata_condition\": metadata,\n"
        "    }\n"
        "    return {\"payload_json\": json.dumps(payload, ensure_ascii=False)}\n"
    )


def _literal_or_empty(value: Any) -> str:
    if _selector_from_template_ref(value):
        return ""
    return _text(value)


def _selector_variable(name: str, value: Any) -> dict[str, Any] | None:
    selector = _selector_from_template_ref(value)
    if not selector:
        return None
    return {"variable": name, "value_selector": selector}


def _retrieval_patch_node_id(http_node_id: str) -> str:
    suffix = http_node_id[-3:] if len(http_node_id) >= 3 else http_node_id
    return f"178309900{suffix}"


def _build_retrieval_payload_node(node: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    data = _node_data(node)
    metadata = payload.get("metadata_condition") if isinstance(payload.get("metadata_condition"), dict) else {}
    knowledge_id = _text(payload.get("knowledge_id"))
    if not knowledge_id:
        return None
    app_id = _text(metadata.get("app_id"))
    if not app_id:
        return None
    node_id = _retrieval_patch_node_id(_text(node.get("id")))
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    x = float(position.get("x") or 0)
    y = float(position.get("y") or 0)
    variables = [
        item
        for item in (
            _selector_variable("query", payload.get("query")),
            _selector_variable("area_name", metadata.get("areaName")),
            _selector_variable("normalized_area", metadata.get("normalized_area")),
            _selector_variable("polished_query", metadata.get("polished_query")),
        )
        if item is not None
    ]
    metadata_defaults = {
        "query": _literal_or_empty(payload.get("query")),
        "workflow_source": _literal_or_empty(metadata.get("workflow_source")) or "dify-http-rag-retrieval",
        "areaName": _literal_or_empty(metadata.get("areaName")),
        "normalized_area": _literal_or_empty(metadata.get("normalized_area")),
        "polished_query": _literal_or_empty(metadata.get("polished_query")),
    }
    code = _retrieval_payload_code(
        app_id=app_id,
        knowledge_id=knowledge_id,
        retrieval_setting=payload.get("retrieval_setting") if isinstance(payload.get("retrieval_setting"), dict) else {},
        metadata_defaults=metadata_defaults,
    )
    title = _text(data.get("title")).replace("MimirQ HTTP检索", "安全构造 MimirQ 检索请求", 1)
    return {
        "data": {
            "code": code,
            "code_language": "python3",
            "desc": "Build a JSON-safe MimirQ retrieval payload. Keeps user text out of raw JSON templates.",
            "outputs": {"payload_json": {"children": None, "type": "string"}},
            "selected": False,
            "title": title,
            "type": "code",
            "variables": variables,
        },
        "height": 114,
        "id": node_id,
        "position": {"x": x - 270.0, "y": y},
        "positionAbsolute": {"x": x - 270.0, "y": y},
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": 244,
    }


def _edge_to_code(edge: dict[str, Any], code_node_id: str) -> dict[str, Any]:
    patched_edge = copy.deepcopy(edge)
    patched_edge["target"] = code_node_id
    patched_edge["targetHandle"] = "target"
    source = _text(patched_edge.get("source"))
    source_handle = _text(patched_edge.get("sourceHandle")) or "source"
    patched_edge["id"] = f"{source}-{source_handle}-{code_node_id}-target"
    data = patched_edge.get("data") if isinstance(patched_edge.get("data"), dict) else {}
    data = {**data, "targetType": "code"}
    patched_edge["data"] = data
    return patched_edge


def _edge_from_code(code_node_id: str, http_node_id: str) -> dict[str, Any]:
    return {
        "data": {
            "isInIteration": False,
            "sourceType": "code",
            "targetType": "http-request",
        },
        "id": f"{code_node_id}-source-{http_node_id}-target",
        "selected": False,
        "source": code_node_id,
        "sourceHandle": "source",
        "target": http_node_id,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


def patch_http_json_template_bodies(workflow: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a workflow copy with MimirQ retrieval JSON bodies built in Code nodes."""
    patched_workflow = copy.deepcopy(workflow)
    graph = patched_workflow.get("graph")
    if not isinstance(graph, dict):
        return patched_workflow, []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return patched_workflow, []

    existing_ids = {_text(node.get("id")) for node in nodes if isinstance(node, dict)}
    patches: list[dict[str, Any]] = []
    nodes_to_append: list[dict[str, Any]] = []
    target_http_ids: set[str] = set()

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = _text(node.get("id"))
        data = _node_data(node)
        if data.get("type") != "http-request":
            continue
        url = _text(data.get("url"))
        if "/api/v1/integrations/dify/retrieval" not in url:
            continue
        entries = _http_json_body_entries(data)
        if len(entries) != 1:
            continue
        value = entries[0].get("value")
        if not isinstance(value, str) or "{{#" not in value or _selector_from_template_ref(value):
            continue
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        payload_node = _build_retrieval_payload_node(node, payload)
        if payload_node is None:
            continue
        payload_node_id = _text(payload_node.get("id"))
        if not payload_node_id or payload_node_id in existing_ids:
            continue
        entries[0]["value"] = f"{{{{#{payload_node_id}.payload_json#}}}}"
        nodes_to_append.append(payload_node)
        existing_ids.add(payload_node_id)
        target_http_ids.add(node_id)
        patches.append(
            {
                "http_node_id": node_id,
                "http_node_title": _text(data.get("title")),
                "payload_node_id": payload_node_id,
                "payload_node_title": _text(payload_node["data"].get("title")),
                "knowledge_id": _text(payload.get("knowledge_id")),
            }
        )

    if not target_http_ids:
        return patched_workflow, []

    patched_edges: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            patched_edges.append(edge)
            continue
        target = _text(edge.get("target"))
        if target not in target_http_ids:
            patched_edges.append(edge)
            continue
        code_node_id = _retrieval_patch_node_id(target)
        patched_edges.append(_edge_to_code(edge, code_node_id))
    for http_node_id in sorted(target_http_ids):
        patched_edges.append(_edge_from_code(_retrieval_patch_node_id(http_node_id), http_node_id))

    graph["nodes"] = nodes + nodes_to_append
    graph["edges"] = patched_edges
    return patched_workflow, patches


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
    prompt_template_leak_warnings = _prompt_template_leak_warnings(nodes)
    http_json_template_warnings = _http_json_template_warnings(nodes)
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
    if prompt_template_leak_warnings:
        summary["prompt_template_leak_warnings"] = len(prompt_template_leak_warnings)
        report["prompt_template_leak_warnings"] = prompt_template_leak_warnings
    if http_json_template_warnings:
        summary["http_json_template_warnings"] = len(http_json_template_warnings)
        report["http_json_template_warnings"] = http_json_template_warnings
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
    parser.add_argument(
        "--preflight-gate",
        action="store_true",
        help="Exit non-zero for the same workflow issues that block changzhou-dify-full-gate preflight.",
    )
    parser.add_argument("--app-id", default="")
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--patched-workflow-out",
        default="",
        help="Write a local workflow JSON copy with regional route conditions patched to Start.areaName.",
    )
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
        if _text(args.patched_workflow_out):
            patched_workflow, patches = patch_area_route_selectors(workflow)
            patched_workflow, prompt_patches = patch_prompt_template_leaks(patched_workflow)
            patched_workflow, http_json_patches = patch_http_json_template_bodies(patched_workflow)
            Path(str(args.patched_workflow_out)).write_text(
                json.dumps(patched_workflow, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
            summary["area_route_patches"] = len(patches)
            report["area_route_patches"] = patches
            summary["prompt_template_leak_patches"] = len(prompt_patches)
            report["prompt_template_leak_patches"] = prompt_patches
            summary["http_json_template_patches"] = len(http_json_patches)
            report["http_json_template_patches"] = http_json_patches
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-workflow-lint] ERR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if bool(args.preflight_gate):
        issue_count = int(summary.get("case_input_violations") or 0) + int(
            summary.get("prompt_template_leak_warnings") or 0
        ) + int(
            summary.get("http_json_template_warnings") or 0
        )
    elif bool(args.case_inputs_only):
        issue_count = int(summary.get("case_input_violations") or 0)
    else:
        issue_count = int(summary.get("hidden_required_start_variables") or 0) + int(
            summary.get("case_input_violations") or 0
        ) + int(
            summary.get("prompt_template_leak_warnings") or 0
        ) + int(
            summary.get("http_json_template_warnings") or 0
        )
    return 0 if issue_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
