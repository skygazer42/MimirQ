from __future__ import annotations

import importlib.util
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
            {"id": "bad-case", "query": "经开区社保卡补卡在哪里办理"},
            {"id": "fallback-key", "query": "天宁区社保卡补卡在哪里办理", "app_inputs": {"areaName": "天宁区"}},
        ],
    )

    assert report["summary"]["case_inputs_checked"] == 3
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
