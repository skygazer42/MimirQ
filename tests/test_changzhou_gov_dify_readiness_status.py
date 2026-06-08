import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_readiness_status.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_readiness_status", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_format_status_prints_failed_root_cause_and_next_action() -> None:
    mod = _load_module()
    report = {
        "generated_at": "2026-06-06T23:56:19Z",
        "artifact_generated_at": {
            "knowledge_map": "2026-06-06T23:56:18Z",
            "console_auth": "2026-06-06T23:56:19Z",
        },
        "summary": {
            "passed": False,
            "root_cause_stage": "console_auth",
            "root_cause_reason": "token_expired",
            "next_action": "Refresh Dify console login with DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD_FILE, then run make dify-console-login.",
            "skipped_stages": ["external_probe", "full_gate"],
        },
        "knowledge_map": {"status": "passed"},
        "mimirq_direct": {"status": "passed"},
        "console_auth": {"status": "failed"},
        "artifacts": {"console_auth": "/tmp/dify_console_check.json"},
    }

    text = mod.format_status(report)

    assert "Changzhou Dify readiness: FAILED" in text
    assert "Generated at: 2026-06-06T23:56:19Z" in text
    assert "Freshness:" in text
    assert "Root cause: console_auth (token_expired)" in text
    assert "Next action: Refresh Dify console login" in text
    assert "Passed stages: knowledge_map, mimirq_direct" in text
    assert "Skipped stages: external_probe, full_gate" in text
    assert "Artifact times: knowledge_map=2026-06-06T23:56:18Z; console_auth=2026-06-06T23:56:19Z" in text
    assert "console_auth=/tmp/dify_console_check.json" in text


def test_format_status_prints_passed_summary() -> None:
    mod = _load_module()
    report = {
        "summary": {"passed": True, "failed_stages": [], "skipped_stages": []},
        "external_probe": {"boundary": {"verdict": "dify_external_boundary_ok"}},
        "artifacts": {"readiness": "/tmp/readiness.json"},
    }

    text = mod.format_status(report)

    assert text.splitlines()[0] == "Changzhou Dify readiness: PASSED"
    assert "Boundary: dify_external_boundary_ok" in text
    assert "Root cause:" not in text


def test_format_markdown_evidence_uses_metrics_without_raw_answers() -> None:
    mod = _load_module()
    report = {
        "generated_at": "2026-06-07T04:49:28Z",
        "summary": {"passed": True, "failed_stages": [], "stage_count": 5},
        "artifacts": {
            "readiness": "/tmp/readiness.json",
            "answers": "/tmp/answers.json",
        },
        "artifact_generated_at": {"full_gate": "2026-06-07T04:49:27Z"},
        "knowledge_map": {
            "status": "passed",
            "summary": {
                "route_count": 7,
                "city_dataset_count": 5,
                "plugin_refs_checked": 2,
                "plugin_refs_invalid": 0,
                "plugin_refs_missing_retrieval_policy": 0,
            },
        },
        "mimirq_direct": {
            "status": "passed",
            "summary": {
                "cases": 13,
                "hit_at_1": 1.0,
                "answer_grounding_rate": 1.0,
                "retrieval_effective_context_rate": 0.94,
                "retrieval_noise_rate": 0.06,
            },
            "source": {"base_url": "http://192.168.3.6:8000", "base_host": "192.168.3.6"},
        },
        "kg_compare": {
            "status": "passed",
            "summary": {"candidate_gate_passed": True, "compared_metrics": 14},
            "candidate_gate": {
                "checks": [
                    {"metric": "kg_noise_rate", "actual": 0.05, "maximum": 0.1, "passed": True},
                ]
            },
        },
        "external_probe": {
            "status": "passed",
            "endpoint_host": "192.168.3.6",
            "boundary": {"verdict": "dify_external_boundary_ok"},
            "summary": {"cases": 13, "dify_hit_nonempty": 13, "probe_errors": 0},
        },
        "full_gate": {
            "status": "passed",
            "stages": {
                "eval": {
                    "summary": {
                        "generated_answer_policy_clean_rate": 1.0,
                        "generated_answer_grounding_rate": 1.0,
                        "generated_answer_fallback_rate": 0.0,
                        "hit_at_1": 0.95,
                        "hit_at_3": 0.99,
                        "answer_grounding_rate": 1.0,
                        "answer_key_point_recall": 1.0,
                        "retrieval_effective_context_rate": 0.94,
                        "retrieval_noise_rate": 0.06,
                    }
                },
                "trace": {
                    "summary": {
                        "empty_retrieval_cases": 0,
                        "route_mismatch_cases": 0,
                        "trace_errors": 0,
                    }
                },
            },
        },
        "answers": [
            {
                "query": "新北区社保卡补卡在哪里办理",
                "answer": "这段真实回答不应进入 Markdown evidence",
            }
        ],
    }

    text = mod.format_markdown_evidence(
        report,
        console_ui_base_url="https://ai.kingdonsoft.com:3000/brainai",
        app_id="app-1",
    )

    assert "# Changzhou Dify/MimirQ Readiness Evidence" in text
    assert "**Status:** PASSED" in text
    assert "dify_external_boundary_ok" in text
    assert "generated_answer_policy_clean_rate" in text
    assert "effective_context_rate=0.94" in text
    assert "noise_rate=0.06" in text
    assert "| retrieval_effective_context_rate | 0.94 |" in text
    assert "| retrieval_noise_rate | 0.06 |" in text
    assert "route_mismatch_cases" in text
    assert "plugin_refs_checked=2" in text
    assert "plugin_refs_invalid=0" in text
    assert "plugin_refs_missing_retrieval_policy=0" in text
    assert "| kg_compare | passed | candidate_gate=true; compared_metrics=14; kg_noise_rate=0.05 |" in text
    assert "| route_mismatch_cases | 0 |" in text
    assert "| empty_retrieval_cases | 0 |" in text
    assert "probe_errors=0" in text
    assert "/tmp/readiness.json" in text
    assert "https://ai.kingdonsoft.com:3000/brainai/app/app-1/workflow" in text
    assert "新北区社保卡补卡在哪里办理" not in text
    assert "这段真实回答不应进入 Markdown evidence" not in text


def test_main_writes_markdown_evidence(tmp_path: Path) -> None:
    mod = _load_module()
    summary_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "evidence.md"
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T04:49:28Z",
                "summary": {"passed": True, "failed_stages": [], "stage_count": 5},
                "external_probe": {"boundary": {"verdict": "dify_external_boundary_ok"}},
                "full_gate": {"stages": {"trace": {"summary": {"route_mismatch_cases": 0}}}},
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--summary", str(summary_path), "--markdown-out", str(markdown_path)])

    assert rc == 0
    text = markdown_path.read_text(encoding="utf-8")
    assert "# Changzhou Dify/MimirQ Readiness Evidence" in text
    assert "**Status:** PASSED" in text


def test_format_status_prints_console_ui_urls_with_base_path() -> None:
    mod = _load_module()
    report = {"summary": {"passed": True}}

    text = mod.format_status(
        report,
        max_age_minutes=0,
        console_ui_base_url="https://ai.kingdonsoft.com:3000/brainai/",
        app_id="app-1",
    )

    assert "Dify console UI: https://ai.kingdonsoft.com:3000/brainai/apps" in text
    assert "Dify workflow UI: https://ai.kingdonsoft.com:3000/brainai/app/app-1/workflow" in text


def test_format_status_prints_mimirq_direct_source_match_state() -> None:
    mod = _load_module()

    matching = mod.format_status(
        {
            "summary": {"passed": True},
            "mimirq_direct": {"source": {"base_url": "http://192.168.3.6:8000", "base_host": "192.168.3.6"}},
            "external_probe": {"endpoint_host": "192.168.3.6"},
        },
        max_age_minutes=0,
    )
    mismatching = mod.format_status(
        {
            "summary": {"passed": True},
            "mimirq_direct": {"source": {"base_url": "http://127.0.0.1:8000", "base_host": "127.0.0.1"}},
            "external_probe": {"endpoint_host": "192.168.3.6"},
        },
        max_age_minutes=0,
    )

    assert "MimirQ direct base: http://192.168.3.6:8000 (matches external endpoint host)" in matching
    assert "MimirQ direct base: http://127.0.0.1:8000 (differs from external endpoint host 192.168.3.6)" in mismatching


def test_format_status_prints_retrieval_quality_summary() -> None:
    mod = _load_module()

    text = mod.format_status(
        {
            "summary": {"passed": True},
            "mimirq_direct": {
                "status": "passed",
                "summary": {
                    "hit_at_1": 0.95,
                    "retrieval_effective_context_rate": 0.94,
                    "retrieval_noise_rate": 0.06,
                },
            },
            "full_gate": {
                "status": "passed",
                "stages": {
                    "eval": {
                        "summary": {
                            "retrieval_effective_context_rate": 0.93,
                            "retrieval_noise_rate": 0.07,
                        }
                    }
                },
            },
        },
        max_age_minutes=0,
    )

    assert (
        "Retrieval quality: direct.hit_at_1=0.95; direct.effective_context_rate=0.94; "
        "direct.noise_rate=0.06; full.effective_context_rate=0.93; full.noise_rate=0.07"
    ) in text


def test_format_status_prints_kg_compare_summary() -> None:
    mod = _load_module()

    text = mod.format_status(
        {
            "summary": {"passed": True},
            "kg_compare": {
                "status": "passed",
                "summary": {
                    "candidate_gate_passed": True,
                    "compared_metrics": 14,
                    "candidate_cases": 13,
                },
                "candidate_gate": {
                    "checks": [
                        {"metric": "kg_noise_rate", "actual": 0.05, "maximum": 0.1, "passed": True},
                    ]
                },
            },
        },
        max_age_minutes=0,
    )

    assert "KG compare: status=passed; candidate_gate=true; compared_metrics=14; kg_noise_rate=0.05" in text
    assert "Passed stages: kg_compare" in text


def test_format_status_prints_knowledge_map_plugin_ref_summary() -> None:
    mod = _load_module()

    text = mod.format_status(
        {
            "summary": {"passed": False},
            "knowledge_map": {
                "status": "failed",
                "summary": {
                    "plugin_refs_checked": 2,
                    "plugin_refs_invalid": 1,
                    "plugin_refs_missing_retrieval_policy": 1,
                },
            },
        },
        max_age_minutes=0,
    )

    assert "Knowledge map plugins: checked=2; invalid=1; missing_policy=1" in text


def test_format_status_prints_non_blocking_full_gate_warnings() -> None:
    mod = _load_module()
    report = {
        "summary": {"passed": True},
        "full_gate": {
            "warning_cases": {
                "eval.generated_answer_missing": ["city-car-replacement-subsidy"],
                "trace.route_compensated": [
                    "xinbei-social-card-reissue-location",
                    "jingkai-social-card-reissue-location",
                ],
                "trace.region_mismatch": ["xinbei-social-card-reissue-location"],
            },
            "warning_diagnoses": {
                "route_compensated_by_retrieval_evidence": [
                    "xinbei-social-card-reissue-location",
                    "jingkai-social-card-reissue-location",
                ],
                "dify_area_extractor_empty": ["xinbei-social-card-reissue-location"],
            },
            "warning_diagnosis_details": {
                "eval.generated_answer_missing": {
                    "city-car-replacement-subsidy": [
                        "grounded=false",
                        "missing_key_points=2025年补贴申请",
                    ]
                },
                "dify_area_extractor_empty": {
                    "xinbei-social-card-reissue-location": [
                        "区域提取器: Failed to extract result from function call or text response, using empty result.",
                        "区域提取器: area=<empty>",
                    ]
                }
            },
            "stages": {
                "preflight": {"summary": {"area_route_warnings": 1, "case_input_violations": 0}},
                "eval": {"summary": {"generated_answer_missing_cases": 1, "generated_answer_fallback_cases": 0}},
                "trace": {
                    "summary": {
                        "node_route_mismatch_cases": 3,
                        "route_compensated_cases": 3,
                        "route_mismatch_cases": 0,
                        "region_mismatch_cases": 3,
                        "fallback_cases": 0,
                        "empty_retrieval_cases": 0,
                        "trace_errors": 0,
                    }
                },
            }
        },
    }

    text = mod.format_status(report, max_age_minutes=0)

    assert (
        "Warnings: preflight.area_route_warnings=1; "
        "eval.generated_answer_missing_cases=1; "
        "trace.node_route_mismatch_cases=3; "
        "trace.route_compensated_cases=3; "
        "trace.region_mismatch_cases=3"
    ) in text
    assert (
        "Warning cases: eval.generated_answer_missing=city-car-replacement-subsidy; "
        "trace.route_compensated=xinbei-social-card-reissue-location,jingkai-social-card-reissue-location; "
        "trace.region_mismatch=xinbei-social-card-reissue-location"
    ) in text
    assert (
        "Warning diagnosis: "
        "route_compensated_by_retrieval_evidence=xinbei-social-card-reissue-location,jingkai-social-card-reissue-location; "
        "dify_area_extractor_empty=xinbei-social-card-reissue-location"
    ) in text
    assert (
        "Warning detail: eval.generated_answer_missing=city-car-replacement-subsidy["
        "grounded=false | missing_key_points=2025年补贴申请]; "
        "dify_area_extractor_empty=xinbei-social-card-reissue-location["
        "区域提取器: Failed to extract result from function call or text response, using empty result. | "
        "区域提取器: area=<empty>]"
    ) in text
    assert "trace.evidence_route_mismatch" not in text
    assert "trace.route_mismatch_cases=0" not in text


def test_format_status_marks_stale_reports() -> None:
    mod = _load_module()
    report = {
        "generated_at": "2026-06-06T23:00:00Z",
        "summary": {"passed": True},
    }

    text = mod.format_status(report, now=datetime(2026, 6, 7, 0, 0, tzinfo=UTC), max_age_minutes=30)

    assert "Freshness: STALE (age=60m, max=30m)" in text


def test_format_status_marks_fresh_reports() -> None:
    mod = _load_module()
    report = {
        "generated_at": "2026-06-06T23:50:00Z",
        "summary": {"passed": True},
    }

    text = mod.format_status(report, now=datetime(2026, 6, 7, 0, 0, tzinfo=UTC), max_age_minutes=30)

    assert "Freshness: fresh (age=10m, max=30m)" in text


def test_format_status_marks_missing_generated_at_unknown() -> None:
    mod = _load_module()
    report = {"summary": {"passed": True}}

    text = mod.format_status(report, now=datetime(2026, 6, 7, 0, 0, tzinfo=UTC), max_age_minutes=30)

    assert "Freshness: unknown (missing generated_at)" in text


def test_main_returns_nonzero_for_failed_summary(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    mod = _load_module()
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps({"summary": {"passed": False, "root_cause_stage": "console_auth"}}), encoding="utf-8")

    rc = mod.main(["--summary", str(path)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Changzhou Dify readiness: FAILED" in captured.out
