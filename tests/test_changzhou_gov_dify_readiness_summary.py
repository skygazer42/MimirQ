import importlib.util
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
            "external_api_name": "MimirQ-192.168.3.6",
            "endpoint": "http://192.168.3.6:8000/api/v1/integrations/dify",
            "endpoint_host": "192.168.3.6",
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
    )

    assert summary == {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_readiness_summary.v1",
        "summary": {"passed": True, "failed_stages": [], "stage_count": 2},
        "artifacts": {"external_probe": "/tmp/probe.json", "full_gate": "/tmp/full_summary.json"},
        "external_probe": {
            "passed": True,
            "failed_conditions": [],
            "endpoint": "http://192.168.3.6:8000/api/v1/integrations/dify",
            "endpoint_host": "192.168.3.6",
            "endpoint_host_is_local": True,
            "external_api_name": "MimirQ-192.168.3.6",
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
    )

    assert summary["summary"] == {"passed": False, "failed_stages": ["external_probe"], "stage_count": 2}
