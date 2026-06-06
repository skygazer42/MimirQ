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
        },
        "summary": {
            "cases": 12,
            "dify_hit_nonempty": 12,
            "mimirq_direct_nonempty": 12,
            "mimirq_direct_schema_valid": 12,
            "probe_errors": 0,
        },
    }
    full_gate = {
        "summary": {"passed": True, "failed_stages": [], "stage_count": 4},
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
        external_probe=external_probe,
        full_gate_summary=full_gate,
        artifacts={"external_probe": "/tmp/probe.json", "full_gate": "/tmp/full_summary.json"},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary == {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_readiness_summary.v1",
        "generated_at": "2026-06-07T01:02:03Z",
        "summary": {"passed": True, "failed_stages": [], "stage_count": 2},
        "artifacts": {"external_probe": "/tmp/probe.json", "full_gate": "/tmp/full_summary.json"},
        "external_probe": {
            "passed": True,
            "failed_conditions": [],
            "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
            "endpoint_host": "192.0.2.6",
            "endpoint_host_is_local": True,
            "external_api_name": "MimirQ-192.0.2.6",
            "summary": external_probe["summary"],
        },
        "full_gate": {
            "passed": True,
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
        external_probe={"gate": {"passed": False, "failed_conditions": ["endpoint_host_is_local"]}},
        full_gate_summary={"summary": {"passed": True, "failed_stages": []}},
        artifacts={},
        generated_at="2026-06-07T01:02:03Z",
    )

    assert summary["summary"] == {"passed": False, "failed_stages": ["external_probe"], "stage_count": 2}


def test_main_writes_failed_summary_when_input_artifacts_are_missing(tmp_path: Path) -> None:
    mod = _load_module()
    out = tmp_path / "readiness.json"

    rc = mod.main(
        [
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
    assert report["summary"] == {"passed": False, "failed_stages": ["external_probe", "full_gate"], "stage_count": 2}
    assert report["external_probe"]["passed"] is False
    assert report["full_gate"]["passed"] is False


def test_main_collects_artifact_generated_at_values(tmp_path: Path) -> None:
    mod = _load_module()
    external_probe = tmp_path / "external.json"
    full_summary = tmp_path / "full_summary.json"
    answers = tmp_path / "answers.json"
    eval_report = tmp_path / "eval.json"
    trace = tmp_path / "trace.json"
    out = tmp_path / "readiness.json"

    external_probe.write_text(
        json.dumps({"generated_at": "2026-06-07T01:00:00Z", "gate": {"passed": True, "failed_conditions": []}}),
        encoding="utf-8",
    )
    full_summary.write_text(
        json.dumps({"generated_at": "2026-06-07T01:04:00Z", "summary": {"passed": True, "failed_stages": []}}),
        encoding="utf-8",
    )
    answers.write_text(json.dumps({"generated_at": "2026-06-07T01:01:00Z"}), encoding="utf-8")
    eval_report.write_text(json.dumps({"generated_at": "2026-06-07T01:02:00Z"}), encoding="utf-8")
    trace.write_text(json.dumps({"generated_at": "2026-06-07T01:03:00Z"}), encoding="utf-8")

    rc = mod.main(
        [
            "--external-probe",
            str(external_probe),
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
        "external_probe": "2026-06-07T01:00:00Z",
        "answers": "2026-06-07T01:01:00Z",
        "eval": "2026-06-07T01:02:00Z",
        "trace": "2026-06-07T01:03:00Z",
        "full_gate": "2026-06-07T01:04:00Z",
    }
