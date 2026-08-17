
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.changzhou_gov_dify_knowledge_map_check import (
    CITY_KNOWLEDGE_ID,
    REQUIRED_DISTRICT_TERMS,
    check_knowledge_map,
)
from scripts.changzhou_gov_dify_readiness_status import (
    format_markdown_evidence,
    format_status,
)
from scripts.changzhou_gov_dify_readiness_summary import build_readiness_summary
from scripts.changzhou_gov_dify_workflow_lint import (
    lint_workflow,
    patch_area_route_selectors,
    patch_http_json_template_bodies,
)
from scripts.dify_3way_benchmark import AppSpec, build_sharing_markdown, main


def _district_route(district: str) -> dict[str, object]:
    return {
        "terms": list(REQUIRED_DISTRICT_TERMS[district]),
        "dataset_ids": [f"route-{district}"],
        "mode": "prepend",
    }


def _knowledge_payload() -> dict[str, object]:
    routes = [_district_route(district) for district in REQUIRED_DISTRICT_TERMS]
    payload: dict[str, object] = {
        CITY_KNOWLEDGE_ID: {
            "dataset_ids": ["city-dataset"],
            "query_routes": routes,
            "strict_query_routes": True,
            "plugin_refs": ["plugin:valid@1.0.0", "bad-ref"],
        }
    }
    for district in REQUIRED_DISTRICT_TERMS:
        payload[f"changzhou_{district}_service"] = {
            "dataset_ids": [f"dataset-{district}"],
            "plugin_refs": [f"plugin:{district}@1.0.0"],
        }
    return payload


def test_check_knowledge_map_preserves_failure_order_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _knowledge_payload()
    city = payload[CITY_KNOWLEDGE_ID]
    assert isinstance(city, dict)
    routes = city["query_routes"]
    assert isinstance(routes, list)

    first_route = routes[0]
    second_route = routes[1]
    assert isinstance(first_route, dict)
    assert isinstance(second_route, dict)
    first_route["dataset_ids"] = []
    second_route["mode"] = "sideways"
    payload.pop("changzhou_天宁区_service")
    payload["changzhou_武进区_service"] = {"dataset_ids": [], "plugin_refs": ["plugin:武进区@1.0.0"]}

    def _resolve(plugin_ref: str) -> dict[str, object]:
        return {} if plugin_ref in {"plugin:武进区@1.0.0"} else {"schema": "mimirq.retrieval_policy.v1"}

    monkeypatch.setattr(
        "scripts.changzhou_gov_dify_knowledge_map_check.resolve_plugin_retrieval_policy",
        _resolve,
    )

    report = check_knowledge_map(payload, generated_at="2026-08-16T00:00:00Z")

    assert report["schema"] == "mimirq.changzhou_gov_service_knowledge.dify_knowledge_map_check.v1"
    assert report["generated_at"] == "2026-08-16T00:00:00Z"
    assert report["summary"] == {
        "passed": False,
        "failed_conditions": [
            "route_dataset_ids_missing:新北区",
            "route_mode_invalid:经开区:sideways",
            "district_knowledge_id_missing:changzhou_天宁区_service",
            "district_knowledge_dataset_ids_missing:changzhou_武进区_service",
            "plugin_ref_invalid:changzhou_city_service:bad-ref",
            "plugin_retrieval_policy_missing:changzhou_武进区_service:plugin:武进区@1.0.0",
        ],
        "city_dataset_count": 1,
        "route_count": len(REQUIRED_DISTRICT_TERMS),
        "district_routes_checked": len(REQUIRED_DISTRICT_TERMS),
        "district_knowledge_ids_checked": len(REQUIRED_DISTRICT_TERMS),
        "plugin_refs_checked": 8,
        "plugin_refs_invalid": 1,
        "plugin_refs_missing_retrieval_policy": 1,
        "route_precedence_issues": 0,
    }
    assert report["district_routes"]["dataset_ids_missing"] == ["新北区"]
    assert report["district_routes"]["invalid_modes"] == [{"district": "经开区", "mode": "sideways"}]
    assert report["district_knowledge_ids"]["missing"] == ["changzhou_天宁区_service"]
    assert report["district_knowledge_ids"]["dataset_ids_missing"] == ["changzhou_武进区_service"]


def test_workflow_lint_and_patchers_preserve_warning_and_patch_shapes() -> None:
    workflow = {
        "graph": {
            "nodes": [
                {
                    "id": "start-node",
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "variables": [
                            {"variable": "areaName", "label": "Area", "required": False},
                            {"variable": "query", "label": "Query", "required": False},
                        ],
                    },
                },
                {
                    "id": "router-node",
                    "data": {
                        "type": "if-else",
                        "title": "区域分流",
                        "cases": [
                            {
                                "conditions": [
                                    {"variable_selector": ["extractor", "area"], "value": "新北区"},
                                ]
                            }
                        ],
                    },
                },
                {
                    "id": "extractor",
                    "data": {"type": "parameter-extractor", "title": "区域提取器"},
                },
                {
                    "id": "consumer-node",
                    "data": {
                        "type": "code",
                        "title": "Consumer",
                        "script": "value={{#start-node.areaName#}}",
                    },
                },
                {
                    "id": "http-node",
                    "position": {"x": 640, "y": 120},
                    "data": {
                        "type": "http-request",
                        "title": "MimirQ HTTP检索",
                        "url": "https://example.invalid/api/v1/integrations/dify/retrieval",
                        "body": {
                            "type": "json",
                            "data": [
                                {
                                    "value": json.dumps(
                                        {
                                            "knowledge_id": "kb-city",
                                            "query": "{{#start-node.query#}}",
                                            "retrieval_setting": {"top_k": 5},
                                            "metadata_condition": {
                                                "app_id": "app-1",
                                                "workflow_source": "dify-http-rag-retrieval",
                                                "areaName": "{{#start-node.areaName#}}",
                                                "normalized_area": "",
                                                "polished_query": "",
                                            },
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            ],
                        },
                    },
                },
            ],
            "edges": [
                {
                    "id": "start-source-http-node-target",
                    "source": "start-node",
                    "sourceHandle": "source",
                    "target": "http-node",
                    "targetHandle": "target",
                    "type": "custom",
                }
            ],
        }
    }

    report = lint_workflow(workflow, cases=[{"id": "case-1", "query": "在哪里办理"}])

    assert report["summary"] == {
        "start_variables": 2,
        "referenced_start_variables": 2,
        "hidden_required_start_variables": 2,
        "area_route_warnings": 1,
        "http_json_template_warnings": 1,
        "case_inputs_checked": 1,
        "case_input_violations": 1,
    }
    assert report["hidden_required_start_variables"][0]["variable"] == "areaName"
    assert report["area_route_warnings"][0]["selector"] == "extractor.area"
    assert report["http_json_template_warnings"][0]["template_selectors"] == [
        "start-node.areaName",
        "start-node.query",
    ]
    assert report["case_input_violations"] == [
        {
            "id": "case-1",
            "query": "在哪里办理",
            "missing_inputs": ["areaName", "query"],
            "selectors": ["start-node.areaName", "start-node.query"],
            "recommendation": "Add dify_inputs.areaName for this case before calling the Dify App API.",
        }
    ]

    patched_routes, route_patches = patch_area_route_selectors(workflow)
    assert route_patches == [
        {
            "routing_node_id": "router-node",
            "routing_node_title": "区域分流",
            "from_selector": "extractor.area",
            "to_selector": "start-node.areaName",
            "conditions_patched": 1,
        }
    ]
    route_selector = patched_routes["graph"]["nodes"][1]["data"]["cases"][0]["conditions"][0]["variable_selector"]
    assert route_selector == ["start-node", "areaName"]

    patched_http, http_patches = patch_http_json_template_bodies(workflow)
    assert http_patches == [
        {
            "http_node_id": "http-node",
            "http_node_title": "MimirQ HTTP检索",
            "payload_node_id": "178309900ode",
            "payload_node_title": "安全构造 MimirQ 检索请求",
            "knowledge_id": "kb-city",
        }
    ]
    graph = patched_http["graph"]
    assert isinstance(graph, dict)
    node_ids = [node["id"] for node in graph["nodes"]]
    assert "178309900ode" in node_ids
    http_value = graph["nodes"][4]["data"]["body"]["data"][0]["value"]
    assert http_value == "{{#178309900ode.payload_json#}}"


def test_build_readiness_summary_preserves_stage_order_and_warning_details() -> None:
    report = build_readiness_summary(
        knowledge_map={
            "summary": {
                "passed": True,
                "route_count": 7,
                "district_knowledge_ids_checked": 7,
                "plugin_refs_checked": 2,
                "plugin_refs_invalid": 0,
                "plugin_refs_missing_retrieval_policy": 0,
            },
            "source": {"plugin_ref": "plugin:city@1.0.0", "plugin_package_hash": "sha256:city"},
        },
        mimirq_direct={
            "gate": {
                "passed": False,
                "checks": [{"metric": "answer_grounding_rate", "passed": False}],
            },
            "summary": {"cases": 2, "hit_at_1": 0.5},
            "source": {"base_url": "http://mimirq.internal", "base_host": "mimirq.internal"},
        },
        kg_compare={"summary": {"passed": True, "candidate_gate_passed": True, "compared_metrics": 3}},
        console_auth={"valid": True, "ttl_seconds": 3600, "min_ttl_seconds": 600},
        external_probe={
            "gate": {"passed": True},
            "summary": {"dify_hit_nonempty": 1, "probe_errors": 0},
            "source": {"endpoint_host": "mimirq.internal"},
            "boundary": {"verdict": "reachable"},
        },
        full_gate_summary={
            "summary": {"passed": True, "failed_stages": []},
            "stages": {
                "trace": {"passed": True, "summary": {"route_mismatch_cases": 0}},
                "eval": {"passed": True, "summary": {"generated_answer_policy_clean_rate": 1.0}},
            },
        },
        artifacts={"summary": "/tmp/readiness.json"},
        generated_at="2026-08-16T01:02:03Z",
        artifact_reports={
            "eval": {
                "gate": {
                    "passed": False,
                    "checks": [{"metric": "answer_grounding_rate", "passed": False}],
                },
                "results": [
                    {
                        "id": "case-1",
                        "generated_answer_quality": {
                            "provided": True,
                            "grounded": False,
                            "missing_key_points": ["材料"],
                        },
                    }
                ],
            },
            "trace": {
                "cases": [
                    {
                        "id": "case-1",
                        "region_matched": False,
                        "regions": [{"region": "未知", "__reason": "extractor empty", "__is_success": 0}],
                    }
                ]
            },
        },
    )

    assert report["summary"] == {
        "passed": False,
        "failed_stages": ["mimirq_direct"],
        "skipped_stages": ["kg_compare", "console_auth", "external_probe", "full_gate"],
        "stage_count": 6,
        "root_cause_stage": "mimirq_direct",
        "root_cause_reason": "quality_gate_failed:answer_grounding_rate",
        "next_action": (
            "Run make changzhou-dify-mimirq-direct-gate and inspect /tmp/changzhou_gov_dify_mimirq_direct_gate.json."
        ),
    }
    assert report["retrieval_audit"]["failure_categories"] == {}
    assert report["full_gate"] == {
        "passed": False,
        "status": "skipped",
        "blocked_by": "mimirq_direct",
    }

    warning_report = build_readiness_summary(
        external_probe={
            "gate": {"passed": True},
            "summary": {"dify_hit_nonempty": 1, "probe_errors": 0},
            "source": {"endpoint_host": "mimirq.internal"},
        },
        full_gate_summary={
            "summary": {"passed": True, "failed_stages": []},
            "stages": {
                "trace": {"passed": True, "summary": {}},
                "eval": {"passed": True, "summary": {}},
            },
        },
        artifacts={},
        artifact_reports={
            "eval": {
                "results": [
                    {
                        "id": "case-1",
                        "generated_answer_quality": {
                            "provided": True,
                            "grounded": False,
                            "missing_key_points": ["材料"],
                        },
                    }
                ]
            },
            "trace": {
                "cases": [
                    {
                        "id": "case-1",
                        "region_matched": False,
                        "regions": [{"region": "未知", "__reason": "extractor empty", "__is_success": 0}],
                    }
                ]
            },
        },
    )
    assert warning_report["full_gate"]["warning_cases"] == {
        "eval.generated_answer_missing": ["case-1"],
        "trace.region_mismatch": ["case-1"],
    }
    assert warning_report["full_gate"]["warning_diagnosis_details"] == {
        "eval.generated_answer_missing": {"case-1": ["grounded=false", "missing_key_points=材料"]},
        "dify_area_extractor_empty": {"case-1": ["区域提取器: extractor empty", "区域提取器: region=未知"]},
    }


def test_format_status_and_markdown_evidence_preserve_sections_and_order() -> None:
    report = {
        "generated_at": "2026-08-16T01:00:00Z",
        "summary": {
            "passed": False,
            "failed_stages": ["mimirq_direct"],
            "skipped_stages": ["kg_compare"],
            "root_cause_stage": "mimirq_direct",
            "root_cause_reason": "quality_gate_failed:answer_grounding_rate",
            "next_action": "Inspect direct gate artifact.",
        },
        "knowledge_map": {
            "status": "passed",
            "summary": {
                "route_count": 7,
                "district_knowledge_ids_checked": 7,
                "plugin_refs_checked": 2,
                "plugin_refs_invalid": 0,
                "plugin_refs_missing_retrieval_policy": 0,
            },
        },
        "mimirq_direct": {
            "status": "failed",
            "summary": {
                "hit_at_1": 0.5,
                "retrieval_effective_context_rate": 0.75,
                "retrieval_noise_rate": 0.1,
            },
            "source": {"base_url": "http://mimirq.internal", "base_host": "mimirq.internal"},
        },
        "kg_compare": {
            "status": "skipped",
            "summary": {"candidate_gate_passed": True, "compared_metrics": 2},
            "candidate_gate": {"checks": [{"metric": "kg_noise_rate", "actual": 0.05}]},
        },
        "console_auth": {"status": "passed", "ttl_seconds": 3600},
        "external_probe": {
            "status": "passed",
            "endpoint_host": "mimirq.internal",
            "summary": {"dify_hit_nonempty": 1, "probe_errors": 0},
            "boundary": {"verdict": "reachable"},
        },
        "full_gate": {
            "status": "passed",
            "warning_cases": {
                "trace.route_mismatch": ["case-1"],
                "eval.generated_answer_missing": ["case-2"],
            },
            "warning_diagnoses": {"fallback": ["case-3"]},
            "warning_diagnosis_details": {"dify_area_extractor_empty": {"case-1": ["区域提取器: region=未知"]}},
            "stages": {
                "eval": {
                    "summary": {
                        "generated_answer_policy_clean_rate": 1.0,
                        "retrieval_effective_context_rate": 0.8,
                        "retrieval_noise_rate": 0.05,
                    }
                },
                "trace": {
                    "summary": {
                        "route_mismatch_cases": 1,
                        "empty_retrieval_cases": 0,
                    }
                },
            },
        },
        "artifact_generated_at": {"summary": "2026-08-16T01:00:00Z"},
        "artifacts": {"summary": "/tmp/readiness.json"},
        "retrieval_audit": {
            "status": "failed",
            "plugin_refs": ["plugin:city@1.0.0"],
            "plugin_package_hashes": ["sha256:city"],
            "gates": [{"name": "knowledge_map"}],
            "failure_categories": {"absence": 1},
            "kg_recommendation": "none",
        },
    }

    status_text = format_status(
        report,
        now=datetime(2026, 8, 16, 1, 10, tzinfo=timezone.utc),
        max_age_minutes=30,
        console_ui_base_url="https://dify.example.com/brainai",
        app_id="app-1",
    )
    assert status_text.splitlines() == [
        "Changzhou Dify readiness: FAILED",
        "Generated at: 2026-08-16T01:00:00Z",
        "Dify console UI: https://dify.example.com/brainai/apps",
        "Dify workflow UI: https://dify.example.com/brainai/app/app-1/workflow",
        "Freshness: fresh (age=10m, max=30m)",
        "Root cause: mimirq_direct (quality_gate_failed:answer_grounding_rate)",
        "Next action: Inspect direct gate artifact.",
        "Passed stages: knowledge_map, console_auth, external_probe, full_gate",
        "Boundary: reachable",
        "Knowledge map plugins: checked=2; invalid=0; missing_policy=0",
        "Retrieval audit: status=failed; plugin_refs=1; package_hashes=1; gates=1; failures=absence; kg=none",
        "KG compare: status=skipped; candidate_gate=true; compared_metrics=2; kg_noise_rate=0.05",
        "MimirQ direct base: http://mimirq.internal (matches external endpoint host)",
        (
            "Retrieval quality: direct.hit_at_1=0.5; direct.effective_context_rate=0.75; "
            "direct.noise_rate=0.1; full.effective_context_rate=0.8; full.noise_rate=0.05"
        ),
        "Warnings: trace.route_mismatch_cases=1; eval.generated_answer_missing_cases=1",
        "Warning cases: trace.route_mismatch=case-1; eval.generated_answer_missing=case-2",
        "Warning diagnosis: fallback=case-3",
        "Warning detail: dify_area_extractor_empty=case-1[区域提取器: region=未知]",
        "Skipped stages: kg_compare",
        "Artifact times: summary=2026-08-16T01:00:00Z",
        "Artifacts: summary=/tmp/readiness.json",
    ]

    markdown = format_markdown_evidence(
        report,
        console_ui_base_url="https://dify.example.com/brainai",
        app_id="app-1",
    )
    assert "## Stage Summary" in markdown
    assert "routes=7; district_ids=7; plugin_refs_checked=2" in markdown
    assert "plugin_refs_invalid=0; plugin_refs_missing_retrieval_policy=0" in markdown
    assert "## Safety" in markdown


def test_build_sharing_markdown_and_generate_only_keep_output_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "generated_at": "2026-08-16T01:02:03Z",
        "summary": {"executed_cases": 8, "skipped_systems": ["dify_native_kb"]},
        "completion_status": {
            "expected_systems": 3,
            "expected_cases": 8,
            "completion_key": "complete_3way_8",
            "complete": False,
        },
        "leaderboard": [
            {
                "rank": 1,
                "system": "dify_http_mimirq",
                "cases": 8,
                "mean_answer_clause_coverage": 0.9,
                "mean_answer_subquestion_coverage": 0.8,
                "mean_wrong_evidence_rate": 0.1,
                "mean_latency_ms": 120.0,
            }
        ],
        "audit_verdict_summary": [
            {
                "system": "dify_http_mimirq",
                "accurate": 6,
                "partially_accurate": 1,
                "insufficient_evidence": 1,
                "no_answer": 0,
                "accurate_rate": 0.75,
                "usable_rate": 0.875,
            }
        ],
        "case_type_advantage": [{"case_type": "mixed", "system": "dify_http_mimirq", "business_score": 0.9}],
        "dimension_advantage": [{"dimension": "材料", "system": "dify_http_mimirq", "business_score": 0.9}],
        "advantage_summary": {
            "overall_best_system": "dify_http_mimirq",
            "strongest_by_win_count": [
                {
                    "system": "dify_http_mimirq",
                    "total_wins": 2,
                    "case_type_wins": 1,
                    "dimension_wins": 1,
                }
            ],
        },
        "top_issue_cases": [
            {
                "system": "dify_http_mimirq",
                "verdict": "insufficient_evidence",
                "business_score": 0.2,
                "source_record_title": "企业登记",
                "query": "企业登记怎么办理",
            }
        ],
        "audit_review": {"jsonl_path": "audit_review.jsonl", "csv_path": "audit_review.csv"},
    }
    markdown = build_sharing_markdown(report)
    assert markdown.startswith("# Dify 3路评测摘要\n")
    assert "## 优势汇总" in markdown
    assert "## 排行榜" in markdown
    assert "- 未纳入完整结论的系统：`dify_native_kb`" in markdown

    cases = [{"id": "case-1", "question": "怎么办理", "knowledge_id": "kb-1"}]
    apps = [AppSpec(label="demo", app_id="app-1", kind="http_to_mimirq", description="Demo", api_key="secret")]

    monkeypatch.setattr("scripts.dify_3way_benchmark.load_prebuilt_cases", lambda _path: cases)
    monkeypatch.setattr("scripts.dify_3way_benchmark.load_app_specs", lambda _raw, _path: apps)

    exit_code = main(
        [
            "--prebuilt-cases",
            "dummy.json",
            "--out-dir",
            str(tmp_path),
            "--generate-only",
        ]
    )

    assert exit_code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == {
        "cases": 1,
        "cases_path": str(tmp_path / "cases_800.json"),
        "apps": 1,
    }
    apps_payload = json.loads((tmp_path / "apps.json").read_text(encoding="utf-8"))
    cases_payload = json.loads((tmp_path / "cases_800.json").read_text(encoding="utf-8"))
    truth_payload = json.loads((tmp_path / "truth_manifest.json").read_text(encoding="utf-8"))

    assert apps_payload == {
        "schema": "mimirq.dify_3way_benchmark.apps.v1",
        "apps": [
            {
                "label": "demo",
                "app_id": "app-1",
                "kind": "http_to_mimirq",
                "description": "Demo",
                "api_key": "<redacted>",
                "mode": "chat",
            }
        ],
    }
    assert cases_payload["schema"] == "mimirq.dify_3way_benchmark.cases.v1"
    assert cases_payload["summary"]["cases"] == 1
    assert truth_payload["schema"] == "mimirq.dify_3way_benchmark.truth_manifest.v1"
    assert truth_payload["items"][0]["case_id"] == "case-1"
