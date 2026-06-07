import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_readiness_summary.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_readiness_summary", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_readiness_summary_combines_probe_and_full_gate() -> None:
    mod = _load_module()
    external_probe = {
        "gate": {"passed": True, "failed_conditions": []},
        "source": {
            "external_api_name": "MimirQ-192.0.2.6",
            "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
            "endpoint_host": "192.0.2.6",
            "endpoint_host_is_local": True,
            "endpoint_host_matches_local_machine": True,
            "endpoint_host_is_loopback": False,
        },
        "summary": {
            "cases": 12,
            "dify_hit_nonempty": 12,
            "mimirq_direct_nonempty": 12,
            "mimirq_direct_schema_valid": 12,
            "probe_errors": 0,
        },
        "boundary": {
            "endpoint_config_ok": True,
            "local_mimirq_direct_ok": True,
            "dify_hit_testing_ok": True,
            "verdict": "dify_external_boundary_ok",
        },
    }
    full_gate = {
        "summary": {
            "passed": True,
            "failed_stages": [],
            "skipped_stages": [],
            "stage_count": 4,
            "root_cause_stage": "",
            "root_cause_reason": "",
            "next_action": "",
        },
        "stages": {
            "collect": {"passed": True, "summary": {"cases": 12, "succeeded": 12, "failed": 0}},
            "eval": {
                "passed": True,
                "summary": {
                    "hit_at_3": 1.0,
                    "generated_answer_key_point_recall": 0.97,
                    "generated_answer_fallback_rate": 0.0,
                },
            },
            "trace": {
                "passed": True,
                "summary": {
                    "cases": 12,
                    "traced": 12,
                    "nonempty_retrieval_cases": 12,
                    "fallback_cases": 0,
                    "trace_errors": 0,
                },
            },
        },
    }

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        mimirq_direct={
            "gate": {"passed": True, "failed": 0, "checks": []},
            "summary": {"cases": 12, "hit_at_1": 1.0, "answer_grounding_rate": 1.0},
            "source": {"base_url": "http://192.0.2.6:8000", "base_host": "192.0.2.6"},
        },
        console_auth={"valid": True, "reason": "ok", "ttl_seconds": 1800, "min_ttl_seconds": 900},
        external_probe=external_probe,
        full_gate_summary=full_gate,
        artifacts={
            "knowledge_map": "/tmp/map.json",
            "console_auth": "/tmp/auth.json",
            "external_probe": "/tmp/probe.json",
            "full_gate": "/tmp/full_summary.json",
        },
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary == {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_readiness_summary.v1",
        "generated_at": "2026-06-07T01:02:03Z",
        "summary": {
            "passed": True,
            "failed_stages": [],
            "skipped_stages": [],
            "stage_count": 5,
            "root_cause_stage": "",
            "root_cause_reason": "",
            "next_action": "",
        },
        "artifacts": {
            "knowledge_map": "/tmp/map.json",
            "console_auth": "/tmp/auth.json",
            "external_probe": "/tmp/probe.json",
            "full_gate": "/tmp/full_summary.json",
        },
        "knowledge_map": {"passed": True, "status": "passed", "failed_conditions": [], "summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        "mimirq_direct": {
            "passed": True,
            "status": "passed",
            "failed_conditions": [],
            "summary": {"cases": 12, "hit_at_1": 1.0, "answer_grounding_rate": 1.0},
            "source": {"base_url": "http://192.0.2.6:8000", "base_host": "192.0.2.6"},
        },
        "console_auth": {"passed": True, "status": "passed", "reason": "ok", "ttl_seconds": 1800, "min_ttl_seconds": 900},
        "external_probe": {
            "passed": True,
            "status": "passed",
            "failed_conditions": [],
            "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
            "endpoint_host": "192.0.2.6",
            "endpoint_host_is_local": True,
            "endpoint_host_matches_local_machine": True,
            "endpoint_host_is_loopback": False,
            "external_api_name": "MimirQ-192.0.2.6",
            "summary": external_probe["summary"],
            "boundary": external_probe["boundary"],
        },
        "full_gate": {
            "passed": True,
            "status": "passed",
            "failed_stages": [],
            "summary": full_gate["summary"],
            "stages": {
                "collect": {"passed": True, "summary": {"cases": 12, "succeeded": 12, "failed": 0}},
                "eval": {
                    "passed": True,
                    "summary": {
                        "hit_at_3": 1.0,
                        "generated_answer_key_point_recall": 0.97,
                        "generated_answer_fallback_rate": 0.0,
                    },
                },
                "trace": {
                    "passed": True,
                    "summary": {
                        "cases": 12,
                        "traced": 12,
                        "nonempty_retrieval_cases": 12,
                        "fallback_cases": 0,
                        "trace_errors": 0,
                    },
                },
            },
        },
    }


def test_build_readiness_summary_marks_failed_source() -> None:
    mod = _load_module()

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": False, "failed_conditions": ["route_missing:经开区"]}},
        console_auth={"valid": False, "reason": "token_expires_soon", "ttl_seconds": 500, "min_ttl_seconds": 900},
        external_probe={"gate": {"passed": False, "failed_conditions": ["endpoint_host_is_loopback"]}},
        full_gate_summary={"summary": {"passed": True, "failed_stages": []}},
        artifacts={},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["summary"] == {
        "passed": False,
        "failed_stages": ["knowledge_map"],
        "skipped_stages": ["console_auth", "external_probe", "full_gate"],
        "stage_count": 4,
        "root_cause_stage": "knowledge_map",
        "root_cause_reason": "route_missing:经开区",
        "next_action": "Run make changzhou-dify-knowledge-map-check and fix DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON.",
    }
    assert summary["knowledge_map"]["status"] == "failed"
    assert summary["console_auth"] == {
        "passed": False,
        "status": "skipped",
        "blocked_by": "knowledge_map",
    }
    assert summary["external_probe"]["status"] == "skipped"
    assert summary["external_probe"]["blocked_by"] == "knowledge_map"


def test_auth_failure_marks_downstream_stages_skipped() -> None:
    mod = _load_module()

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        mimirq_direct={"gate": {"passed": True, "failed": 0, "checks": []}, "summary": {"hit_at_1": 1.0}},
        console_auth={"valid": False, "reason": "token_expired", "ttl_seconds": -10, "min_ttl_seconds": 900},
        external_probe={},
        full_gate_summary={},
        artifacts={},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["summary"] == {
        "passed": False,
        "failed_stages": ["console_auth"],
        "skipped_stages": ["external_probe", "full_gate"],
        "stage_count": 5,
        "root_cause_stage": "console_auth",
        "root_cause_reason": "token_expired",
        "next_action": "Refresh Dify console login with DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD_FILE, then run make dify-console-login.",
    }
    assert summary["knowledge_map"]["status"] == "passed"
    assert summary["mimirq_direct"]["status"] == "passed"
    assert summary["console_auth"]["status"] == "failed"
    assert summary["external_probe"]["status"] == "skipped"
    assert summary["external_probe"]["blocked_by"] == "console_auth"
    assert summary["full_gate"]["status"] == "skipped"
    assert summary["full_gate"]["blocked_by"] == "console_auth"


def test_mimirq_direct_failure_blocks_dify_remote_stages() -> None:
    mod = _load_module()

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        mimirq_direct={
            "gate": {
                "passed": False,
                "failed": 1,
                "checks": [{"metric": "hit_at_1", "actual": 0.9, "minimum": 1.0, "passed": False}],
            },
            "summary": {"cases": 12, "hit_at_1": 0.9},
        },
        console_auth={"valid": True, "reason": "ok", "ttl_seconds": 1800, "min_ttl_seconds": 900},
        external_probe={"gate": {"passed": True, "failed_conditions": []}},
        full_gate_summary={"summary": {"passed": True, "failed_stages": []}},
        artifacts={},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["summary"] == {
        "passed": False,
        "failed_stages": ["mimirq_direct"],
        "skipped_stages": ["console_auth", "external_probe", "full_gate"],
        "stage_count": 5,
        "root_cause_stage": "mimirq_direct",
        "root_cause_reason": "quality_gate_failed:hit_at_1",
        "next_action": "Run make changzhou-dify-mimirq-direct-gate and inspect /tmp/changzhou_gov_dify_mimirq_direct_gate.json.",
    }
    assert summary["knowledge_map"]["status"] == "passed"
    assert summary["mimirq_direct"]["status"] == "failed"
    assert summary["console_auth"]["status"] == "skipped"
    assert summary["console_auth"]["blocked_by"] == "mimirq_direct"


def test_build_readiness_summary_prefers_latest_eval_artifact_summary() -> None:
    mod = _load_module()

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        mimirq_direct={"gate": {"passed": True, "failed": 0, "checks": []}, "summary": {"hit_at_1": 1.0}},
        console_auth={"valid": True, "reason": "ok", "ttl_seconds": 1800, "min_ttl_seconds": 900},
        external_probe={"gate": {"passed": True, "failed_conditions": []}},
        full_gate_summary={
            "summary": {"passed": True, "failed_stages": []},
            "stages": {
                "eval": {
                    "passed": True,
                    "summary": {
                        "generated_answer_grounding_rate": 0.9166666666666666,
                        "generated_answer_key_point_recall": 0.9714285714285714,
                        "generated_answer_missing_cases": 1,
                    },
                }
            },
        },
        artifacts={},
        artifact_reports={
            "eval": {
                "summary": {
                    "generated_answer_grounding_rate": 1.0,
                    "generated_answer_key_point_recall": 1.0,
                    "generated_answer_missing_cases": 0,
                },
                "results": [],
            }
        },
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["full_gate"]["stages"]["eval"]["summary"] == {
        "generated_answer_grounding_rate": 1.0,
        "generated_answer_key_point_recall": 1.0,
        "generated_answer_missing_cases": 0,
    }
    assert "warning_cases" not in summary["full_gate"]


def test_loopback_external_endpoint_gets_specific_next_action() -> None:
    mod = _load_module()

    summary = mod.build_readiness_summary(
        knowledge_map={"summary": {"passed": True, "failed_conditions": [], "route_count": 7}},
        console_auth={"valid": True, "reason": "ok", "ttl_seconds": 1800, "min_ttl_seconds": 900},
        external_probe={
            "gate": {"passed": False, "failed_conditions": ["endpoint_host_is_loopback"]},
            "source": {
                "endpoint": "http://127.0.0.1:8000/api/v1/integrations/dify",
                "endpoint_host": "127.0.0.1",
                "endpoint_host_is_loopback": True,
            },
        },
        full_gate_summary={"summary": {"passed": True, "failed_stages": []}},
        artifacts={},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["summary"]["failed_stages"] == ["external_probe"]
    assert summary["summary"]["root_cause_reason"] == "endpoint_host_is_loopback"
    assert summary["summary"]["next_action"] == (
        "Set Dify external knowledge endpoint to a MimirQ URL reachable from the Dify server, not localhost."
    )
    assert summary["external_probe"]["endpoint_host_is_loopback"] is True
    assert summary["full_gate"]["status"] == "skipped"
    assert summary["full_gate"]["blocked_by"] == "external_probe"


def test_main_writes_failed_summary_when_input_artifacts_are_missing(tmp_path: Path) -> None:
    mod = _load_module()
    out = tmp_path / "readiness.json"

    rc = mod.main(
        [
            "--knowledge-map",
            str(tmp_path / "missing-map.json"),
            "--console-auth",
            str(tmp_path / "missing-auth.json"),
            "--external-probe",
            str(tmp_path / "missing-probe.json"),
            "--full-summary",
            str(tmp_path / "missing-full.json"),
            "--out",
            str(out),
        ]
    )

    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"] == {
        "passed": False,
        "failed_stages": ["knowledge_map"],
        "skipped_stages": ["console_auth", "external_probe", "full_gate"],
        "stage_count": 4,
        "root_cause_stage": "knowledge_map",
        "root_cause_reason": "missing_or_invalid_knowledge_map",
        "next_action": "Run make changzhou-dify-knowledge-map-check and fix DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON.",
    }
    assert report["knowledge_map"]["passed"] is False
    assert report["knowledge_map"]["status"] == "failed"
    assert report["console_auth"]["status"] == "skipped"
    assert report["console_auth"]["blocked_by"] == "knowledge_map"
    assert report["external_probe"]["status"] == "skipped"
    assert report["external_probe"]["blocked_by"] == "knowledge_map"
    assert report["full_gate"]["status"] == "skipped"
    assert report["full_gate"]["blocked_by"] == "knowledge_map"


def test_main_collects_artifact_generated_at_values(tmp_path: Path) -> None:
    mod = _load_module()
    external_probe = tmp_path / "external.json"
    full_summary = tmp_path / "full_summary.json"
    knowledge_map = tmp_path / "map.json"
    mimirq_direct = tmp_path / "mimirq_direct.json"
    console_auth = tmp_path / "auth.json"
    answers = tmp_path / "answers.json"
    eval_report = tmp_path / "eval.json"
    trace = tmp_path / "trace.json"
    out = tmp_path / "readiness.json"

    knowledge_map.write_text(
        json.dumps({"generated_at": "2026-06-07T00:59:00Z", "summary": {"passed": True, "failed_conditions": []}}),
        encoding="utf-8",
    )
    console_auth.write_text(
        json.dumps({"generated_at": "2026-06-07T00:59:30Z", "valid": True, "reason": "ok", "ttl_seconds": 1800}),
        encoding="utf-8",
    )
    mimirq_direct.write_text(
        json.dumps({"generated_at": "2026-06-07T00:59:45Z", "gate": {"passed": True, "checks": []}}),
        encoding="utf-8",
    )
    external_probe.write_text(
        json.dumps({"generated_at": "2026-06-07T01:00:00Z", "gate": {"passed": True, "failed_conditions": []}}),
        encoding="utf-8",
    )
    full_summary.write_text(
        json.dumps({"generated_at": "2026-06-07T01:04:00Z", "summary": {"passed": True, "failed_stages": []}}),
        encoding="utf-8",
    )
    answers.write_text(json.dumps({"generated_at": "2026-06-07T01:01:00Z"}), encoding="utf-8")
    eval_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T01:02:00Z",
                "results": [
                    {
                        "id": "city-car-replacement-subsidy",
                        "generated_answer_quality": {
                            "provided": True,
                            "fallback": False,
                            "grounded": False,
                            "missing_key_points": ["2025年补贴申请"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    trace.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T01:03:00Z",
                "cases": [
                    {
                        "id": "xinbei-social-card-reissue-location",
                        "node_route_matched": False,
                        "route_compensated": True,
                        "route_matched": True,
                        "region_matched": False,
                        "regions": [
                            "未知",
                            {
                                "__is_success": 0,
                                "__reason": "Failed to extract result from function call or text response, using empty result.",
                                "area": "",
                            },
                        ],
                        "fallback": False,
                    },
                    {
                        "id": "one-thing-social-card-operation",
                        "node_route_matched": True,
                        "route_matched": True,
                        "evidence_route_matched": False,
                        "region_matched": True,
                        "fallback": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--external-probe",
            str(external_probe),
            "--knowledge-map",
            str(knowledge_map),
            "--console-auth",
            str(console_auth),
            "--mimirq-direct",
            str(mimirq_direct),
            "--full-summary",
            str(full_summary),
            "--answers",
            str(answers),
            "--eval",
            str(eval_report),
            "--trace",
            str(trace),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["artifact_generated_at"] == {
        "knowledge_map": "2026-06-07T00:59:00Z",
        "console_auth": "2026-06-07T00:59:30Z",
        "mimirq_direct": "2026-06-07T00:59:45Z",
        "external_probe": "2026-06-07T01:00:00Z",
        "answers": "2026-06-07T01:01:00Z",
        "eval": "2026-06-07T01:02:00Z",
        "trace": "2026-06-07T01:03:00Z",
        "full_gate": "2026-06-07T01:04:00Z",
    }
    assert report["full_gate"]["warning_cases"] == {
        "eval.generated_answer_missing": ["city-car-replacement-subsidy"],
        "trace.node_route_mismatch": ["xinbei-social-card-reissue-location"],
        "trace.route_compensated": ["xinbei-social-card-reissue-location"],
        "trace.region_mismatch": ["xinbei-social-card-reissue-location"],
    }
    assert report["full_gate"]["warning_diagnoses"] == {
        "route_compensated_by_retrieval_evidence": ["xinbei-social-card-reissue-location"],
        "dify_area_extractor_empty": ["xinbei-social-card-reissue-location"],
    }
    assert report["full_gate"]["warning_diagnosis_details"] == {
        "eval.generated_answer_missing": {
            "city-car-replacement-subsidy": [
                "grounded=false",
                "missing_key_points=2025年补贴申请",
            ]
        },
        "dify_area_extractor_empty": {
            "xinbei-social-card-reissue-location": [
                "区域提取器: region=未知",
                "区域提取器: Failed to extract result from function call or text response, using empty result.",
                "区域提取器: area=<empty>",
            ]
        }
    }
