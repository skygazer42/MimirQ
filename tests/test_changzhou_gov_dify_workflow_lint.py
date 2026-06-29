from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_workflow_lint.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_workflow_lint", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _workflow(*, required: bool = False, default: str = "") -> dict:
    variable: dict = {
        "label": "区域",
        "required": required,
        "type": "text-input",
        "variable": "areaName",
    }
    if default:
        variable["default"] = default
    return {
        "graph": {
            "nodes": [
                {
                    "id": "1711528914102",
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "variables": [variable],
                    },
                },
                {
                    "id": "1742967080646",
                    "data": {
                        "type": "if-else",
                        "title": "区域条件分支",
                        "cases": [
                            {
                                "conditions": [
                                    {
                                        "variable_selector": ["1711528914102", "areaName"],
                                        "comparison_operator": "contains",
                                        "value": "经开区",
                                    }
                                ]
                            }
                        ],
                    },
                },
                {
                    "id": "1745223008372",
                    "data": {
                        "type": "code",
                        "title": "合并知识库知识",
                        "code": "return inputs['#1711528914102.areaName#']",
                    },
                },
            ]
        }
    }


def test_lint_workflow_reports_non_required_referenced_start_variable() -> None:
    mod = _load_module()

    report = mod.lint_workflow(_workflow())

    assert report["summary"] == {
        "start_variables": 1,
        "referenced_start_variables": 1,
        "hidden_required_start_variables": 1,
    }
    assert report["hidden_required_start_variables"] == [
        {
            "start_node_id": "1711528914102",
            "variable": "areaName",
            "selector": "1711528914102.areaName",
            "label": "区域",
            "required": False,
            "has_default": False,
            "reference_count": 2,
            "references": [
                {
                    "node_id": "1742967080646",
                    "node_title": "区域条件分支",
                    "node_type": "if-else",
                    "path": "graph.nodes[1].data.cases[0].conditions[0].variable_selector",
                },
                {
                    "node_id": "1745223008372",
                    "node_title": "合并知识库知识",
                    "node_type": "code",
                    "path": "graph.nodes[2].data.code",
                },
            ],
            "recommendation": "Pass inputs.areaName or add a Dify workflow default/fallback before referencing this variable.",
        }
    ]


def test_lint_workflow_does_not_report_required_or_defaulted_start_variables() -> None:
    mod = _load_module()

    required_report = mod.lint_workflow(_workflow(required=True))
    defaulted_report = mod.lint_workflow(_workflow(default="常州市"))

    assert required_report["summary"]["hidden_required_start_variables"] == 0
    assert required_report["hidden_required_start_variables"] == []
    assert defaulted_report["summary"]["hidden_required_start_variables"] == 0
    assert defaulted_report["hidden_required_start_variables"] == []


def test_lint_workflow_reports_cases_missing_hidden_required_inputs() -> None:
    mod = _load_module()

    report = mod.lint_workflow(
        _workflow(),
        cases=[
            {"id": "ok-case", "query": "经开区社保卡补卡在哪里办理", "dify_inputs": {"areaName": "经开区"}},
            {"id": "top-level-area", "query": "申请表下载", "areaName": "常州市本级"},
            {"id": "bad-case", "query": "经开区社保卡补卡在哪里办理"},
            {"id": "fallback-key", "query": "天宁区社保卡补卡在哪里办理", "app_inputs": {"areaName": "天宁区"}},
        ],
    )

    assert report["summary"]["case_inputs_checked"] == 4
    assert report["summary"]["case_input_violations"] == 1
    assert report["case_input_violations"] == [
        {
            "id": "bad-case",
            "query": "经开区社保卡补卡在哪里办理",
            "missing_inputs": ["areaName"],
            "selectors": ["1711528914102.areaName"],
            "recommendation": "Add dify_inputs.areaName for this case before calling the Dify App API.",
        }
    ]


def test_lint_workflow_warns_when_area_route_ignores_start_area_name() -> None:
    mod = _load_module()
    workflow = _area_route_workflow()

    report = mod.lint_workflow(workflow)

    assert report["summary"]["area_route_warnings"] == 1
    assert report["area_route_warnings"] == [
        {
            "routing_node_id": "route-1",
            "routing_node_title": "区域条件分支",
            "selector": "extract-1.region",
            "expected_selector": "start-1.areaName",
            "source_node_id": "extract-1",
            "source_node_title": "区域提取器",
            "source_node_type": "parameter-extractor",
            "condition_values": ["新北"],
            "recommendation": "Route regional knowledge from inputs.areaName directly, or normalize it deterministically before the area branch.",
        }
    ]


def test_patch_area_route_selectors_rewrites_route_to_start_area_name_without_mutating_source() -> None:
    mod = _load_module()
    workflow = _area_route_workflow()

    patched, patches = mod.patch_area_route_selectors(workflow)

    assert workflow["graph"]["nodes"][2]["data"]["cases"][0]["conditions"][0]["variable_selector"] == [
        "extract-1",
        "region",
    ]
    assert patched["graph"]["nodes"][2]["data"]["cases"][0]["conditions"][0]["variable_selector"] == [
        "start-1",
        "areaName",
    ]
    assert patches == [
        {
            "routing_node_id": "route-1",
            "routing_node_title": "区域条件分支",
            "from_selector": "extract-1.region",
            "to_selector": "start-1.areaName",
            "conditions_patched": 1,
        }
    ]
    assert mod.lint_workflow(patched)["summary"].get("area_route_warnings", 0) == 0


def test_lint_workflow_reports_prompt_template_leakage() -> None:
    mod = _load_module()

    report = mod.lint_workflow(_prompt_leak_workflow())

    assert report["summary"]["prompt_template_leak_warnings"] == 1
    assert report["prompt_template_leak_warnings"] == [
        {
            "node_id": "llm-1",
            "node_title": "LLM综合回复（一件事及QA）",
            "node_type": "llm",
            "path": "graph.nodes[0].data.prompt_template[0].text",
            "forbidden_phrases": ["必须按顺序包含以下标题", "知识库内容中有", "输出此部分内容"],
            "recommendation": "Rewrite the prompt as model instructions only; do not include user-visible template-control phrases.",
        }
    ]


def test_patch_prompt_template_leaks_rewrites_prompt_without_mutating_source() -> None:
    mod = _load_module()
    workflow = _prompt_leak_workflow()

    patched, patches = mod.patch_prompt_template_leaks(workflow)

    original_text = workflow["graph"]["nodes"][0]["data"]["prompt_template"][0]["text"]
    patched_text = patched["graph"]["nodes"][0]["data"]["prompt_template"][0]["text"]
    assert "必须按顺序包含以下标题" in original_text
    assert "必须按顺序包含以下标题" not in patched_text
    assert "知识库内容中有" not in patched_text
    assert "输出此部分内容" not in patched_text
    assert patches == [
        {
            "node_id": "llm-1",
            "node_title": "LLM综合回复（一件事及QA）",
            "path": "graph.nodes[0].data.prompt_template[0].text",
            "forbidden_phrases": ["必须按顺序包含以下标题", "知识库内容中有", "输出此部分内容"],
        }
    ]
    assert mod.lint_workflow(patched)["summary"].get("prompt_template_leak_warnings", 0) == 0


def test_lint_workflow_reports_http_json_template_body() -> None:
    mod = _load_module()

    report = mod.lint_workflow(_http_json_template_workflow())

    assert report["summary"]["http_json_template_warnings"] == 1
    assert report["http_json_template_warnings"] == [
        {
            "node_id": "178310100008",
            "node_title": "MimirQ HTTP检索 - 常州市政务服务",
            "node_type": "http-request",
            "path": "graph.nodes[1].data.body.data[0].value",
            "template_selectors": [
                "1711528914102.areaName",
                "1769586833805.area",
                "sys.query",
            ],
            "recommendation": (
                "Build the HTTP JSON body in a Code node with json.dumps, then reference "
                "that node's payload_json as the whole body value."
            ),
        }
    ]


def test_patch_http_json_template_bodies_adds_payload_node_and_rewires_edges() -> None:
    mod = _load_module()
    workflow = _http_json_template_workflow()

    patched, patches = mod.patch_http_json_template_bodies(workflow)

    assert workflow["graph"]["nodes"][1]["data"]["body"]["data"][0]["value"].startswith("{")
    assert patches == [
        {
            "http_node_id": "178310100008",
            "http_node_title": "MimirQ HTTP检索 - 常州市政务服务",
            "payload_node_id": "178309900008",
            "payload_node_title": "安全构造 MimirQ 检索请求 - 常州市政务服务",
            "knowledge_id": "changzhou_city_service",
        }
    ]
    http_node = next(node for node in patched["graph"]["nodes"] if node["id"] == "178310100008")
    payload_node = next(node for node in patched["graph"]["nodes"] if node["id"] == "178309900008")
    assert http_node["data"]["body"]["data"][0]["value"] == "{{#178309900008.payload_json#}}"
    assert payload_node["data"]["type"] == "code"
    assert payload_node["data"]["outputs"] == {"payload_json": {"children": None, "type": "string"}}
    assert payload_node["data"]["variables"] == [
        {"variable": "query", "value_selector": ["sys", "query"]},
        {"variable": "area_name", "value_selector": ["1711528914102", "areaName"]},
        {"variable": "normalized_area", "value_selector": ["1769586833805", "area"]},
        {"variable": "polished_query", "value_selector": ["sys", "query"]},
    ]
    edges = patched["graph"]["edges"]
    assert any(edge["source"] == "route-1" and edge["target"] == "178309900008" for edge in edges)
    assert any(edge["source"] == "178309900008" and edge["target"] == "178310100008" for edge in edges)
    assert mod.lint_workflow(patched)["summary"].get("http_json_template_warnings", 0) == 0


def test_main_writes_patched_workflow_for_area_route_warnings(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    out_path = tmp_path / "report.json"
    patched_path = tmp_path / "workflow.patched.json"
    workflow_path.write_text(json.dumps(_area_route_workflow(), ensure_ascii=False), encoding="utf-8")

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--out",
            str(out_path),
            "--patched-workflow-out",
            str(patched_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    patched = json.loads(patched_path.read_text(encoding="utf-8"))
    patched_report = mod.lint_workflow(patched)
    assert exit_code == 0
    assert report["summary"]["area_route_patches"] == 1
    assert report["area_route_patches"][0]["conditions_patched"] == 1
    assert patched_report["summary"].get("area_route_warnings", 0) == 0


def test_main_writes_patched_workflow_for_http_json_template_bodies(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    out_path = tmp_path / "report.json"
    patched_path = tmp_path / "workflow.patched.json"
    workflow_path.write_text(json.dumps(_http_json_template_workflow(), ensure_ascii=False), encoding="utf-8")

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--out",
            str(out_path),
            "--patched-workflow-out",
            str(patched_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    patched = json.loads(patched_path.read_text(encoding="utf-8"))
    patched_report = mod.lint_workflow(patched)
    assert exit_code == 1
    assert report["summary"]["http_json_template_warnings"] == 1
    assert report["summary"]["http_json_template_patches"] == 1
    assert patched_report["summary"].get("http_json_template_warnings", 0) == 0


def test_main_writes_patched_workflow_for_prompt_template_leaks(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    out_path = tmp_path / "report.json"
    patched_path = tmp_path / "workflow.patched.json"
    workflow_path.write_text(json.dumps(_prompt_leak_workflow(), ensure_ascii=False), encoding="utf-8")

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--out",
            str(out_path),
            "--patched-workflow-out",
            str(patched_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    patched = json.loads(patched_path.read_text(encoding="utf-8"))
    patched_report = mod.lint_workflow(patched)
    assert exit_code == 1
    assert report["summary"]["prompt_template_leak_warnings"] == 1
    assert report["summary"]["prompt_template_leak_patches"] == 1
    assert patched_report["summary"].get("prompt_template_leak_warnings", 0) == 0


def _area_route_workflow() -> dict:
    return {
        "graph": {
            "nodes": [
                {
                    "id": "start-1",
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "variables": [{"label": "区域", "required": False, "type": "text-input", "variable": "areaName"}],
                    },
                },
                {
                    "id": "extract-1",
                    "data": {
                        "type": "parameter-extractor",
                        "title": "区域提取器",
                        "query": ["sys", "query"],
                        "parameters": [{"name": "region", "type": "string"}],
                    },
                },
                {
                    "id": "route-1",
                    "data": {
                        "type": "if-else",
                        "title": "区域条件分支",
                        "cases": [
                            {
                                "conditions": [
                                    {
                                        "variable_selector": ["extract-1", "region"],
                                        "comparison_operator": "contains",
                                        "value": "新北",
                                    }
                                ]
                            }
                        ],
                    },
                },
            ]
        }
    }


def _prompt_leak_workflow() -> dict:
    return {
        "graph": {
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {
                        "type": "llm",
                        "title": "LLM综合回复（一件事及QA）",
                        "prompt_template": [
                            {
                                "role": "system",
                                "text": (
                                    "### 应答模版\n"
                                    "必须按顺序包含以下标题：📌【涉及事项】→📋【办理须知】\n"
                                    "一件事系统操作指引说明（知识库内容中有一件事系统操作指引相关内容，输出此部分内容）"
                                ),
                            }
                        ],
                    },
                }
            ]
        }
    }


def _http_json_template_workflow() -> dict:
    body_value = json.dumps(
        {
            "knowledge_id": "changzhou_city_service",
            "query": "{{#sys.query#}}",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
            "metadata_condition": {
                "app_id": "00000000-0000-0000-0000-000000000002",
                "workflow_source": "dify-http-rag-retrieval",
                "areaName": "{{#1711528914102.areaName#}}",
                "normalized_area": "{{#1769586833805.area#}}",
                "polished_query": "{{#sys.query#}}",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "graph": {
            "nodes": [
                {
                    "id": "route-1",
                    "data": {
                        "type": "if-else",
                        "title": "区域条件分支",
                    },
                    "position": {"x": 100, "y": 100},
                    "positionAbsolute": {"x": 100, "y": 100},
                },
                {
                    "id": "178310100008",
                    "data": {
                        "type": "http-request",
                        "title": "MimirQ HTTP检索 - 常州市政务服务",
                        "url": "http://192.0.2.6:8000/api/v1/integrations/dify/retrieval",
                        "body": {
                            "type": "json",
                            "data": [{"key": "", "type": "text", "value": body_value}],
                        },
                    },
                    "position": {"x": 400, "y": 100},
                    "positionAbsolute": {"x": 400, "y": 100},
                },
            ],
            "edges": [
                {
                    "id": "route-1-false-178310100008-target",
                    "source": "route-1",
                    "sourceHandle": "false",
                    "target": "178310100008",
                    "targetHandle": "target",
                    "type": "custom",
                    "data": {
                        "isInIteration": False,
                        "sourceType": "if-else",
                        "targetType": "http-request",
                    },
                }
            ],
        }
    }


def test_main_case_inputs_only_ignores_workflow_warning_when_cases_are_complete(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "report.json"
    workflow_path.write_text(json.dumps(_workflow(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "ok-case",
                        "query": "经开区社保卡补卡在哪里办理",
                        "dify_inputs": {"areaName": "经开区"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--cases",
            str(cases_path),
            "--case-inputs-only",
            "--out",
            str(out_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["summary"]["hidden_required_start_variables"] == 1
    assert report["summary"]["case_input_violations"] == 0


def test_main_case_inputs_only_fails_when_cases_miss_inputs(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "report.json"
    workflow_path.write_text(json.dumps(_workflow(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(
        json.dumps({"cases": [{"id": "bad-case", "query": "经开区社保卡补卡在哪里办理"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--cases",
            str(cases_path),
            "--case-inputs-only",
            "--out",
            str(out_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report["summary"]["case_input_violations"] == 1


def test_main_preflight_gate_ignores_hidden_start_when_cases_are_complete(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "report.json"
    workflow_path.write_text(json.dumps(_workflow(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "ok-case",
                        "query": "经开区社保卡补卡在哪里办理",
                        "dify_inputs": {"areaName": "经开区"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--cases",
            str(cases_path),
            "--preflight-gate",
            "--out",
            str(out_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["summary"]["hidden_required_start_variables"] == 1
    assert report["summary"]["case_input_violations"] == 0


def test_main_preflight_gate_fails_when_prompt_template_leaks(tmp_path: Path) -> None:
    mod = _load_module()
    workflow_path = tmp_path / "workflow.json"
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "report.json"
    workflow_path.write_text(json.dumps(_prompt_leak_workflow(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")

    exit_code = mod.main(
        [
            "--workflow-json",
            str(workflow_path),
            "--cases",
            str(cases_path),
            "--preflight-gate",
            "--out",
            str(out_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report["summary"]["prompt_template_leak_warnings"] == 1
