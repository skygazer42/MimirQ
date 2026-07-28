import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "must_recall_provenance_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("must_recall_provenance_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _write_run_json(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "run.detail.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_run_gate_accepts_wrapped_summary_metrics(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "run": {
                "summary": {
                    "must_recall_pass_rate": 1.0,
                    "must_recall_passed_cases": 2,
                    "must_recall_cases_total": 2,
                    "provenance_integrity_rate": 1.0,
                    "provenance_passed_cases": 2,
                    "provenance_cases_total": 2,
                }
            },
            "items": [],
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is True
    assert result["summary"]["total_cases"] == 2
    assert result["summary"]["must_recall_pass_rate"] == 1.0
    assert result["summary"]["provenance_integrity_rate"] == 1.0


def test_run_gate_uses_item_meta_status_and_booleans(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "run": {"summary": {}},
            "items": [
                {"meta": {"must_recall_status": "passed", "provenance_integrity_passed": True}},
                {"meta": {"must_recall_passed": True, "provenance_integrity_passed": True}},
            ],
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is True
    assert result["summary"]["total_cases"] == 2
    assert result["summary"]["must_recall_passed_cases"] == 2
    assert result["summary"]["provenance_passed_cases"] == 2


def test_run_gate_fails_closed_for_false_and_missing_item_evidence(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "items": [
                {"meta": {"must_recall_passed": False, "provenance_integrity_passed": False}},
                {"meta": {}},
            ]
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is False
    assert result["summary"]["total_cases"] == 2
    assert result["summary"]["must_recall_pass_rate"] == 0.0
    assert result["summary"]["provenance_integrity_rate"] == 0.0
    assert "must_recall_pass_rate_below_threshold" in result["failures"]
    assert "provenance_integrity_rate_below_threshold" in result["failures"]


def test_run_gate_strict_provenance_requires_capsule_not_summary_only(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "run": {
                "summary": {
                    "provenance_integrity_rate": 1.0,
                    "provenance_cases_passed": 1,
                    "provenance_cases_total": 1,
                }
            },
            "items": [{"meta": {"provenance_integrity_passed": True}}],
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=0.0,
        provenance_min=1.0,
        strict_integrity=True,
    )

    assert result["passed"] is False
    assert result["summary"]["provenance_integrity_rate"] == 0.0
    assert "provenance_integrity_rate_below_threshold" in result["failures"]


def test_run_gate_prefers_explicit_item_failures_over_passing_summary(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "run": {
                "summary": {
                    "must_recall_pass_rate": 1.0,
                    "must_recall_passed_cases": 1,
                    "must_recall_cases_total": 1,
                    "provenance_integrity_rate": 1.0,
                    "provenance_passed_cases": 1,
                    "provenance_cases_total": 1,
                }
            },
            "items": [
                {"meta": {"must_recall_passed": False, "provenance_integrity_passed": False}},
            ],
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is False
    assert result["summary"]["must_recall_pass_rate"] == 0.0
    assert result["summary"]["provenance_integrity_rate"] == 0.0


def test_run_gate_does_not_override_explicit_provenance_failure_with_nonstrict_capsule(tmp_path: Path) -> None:
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule

    mod = _load_module()
    capsule = build_evidence_capsule(
        query_for_retrieval="retry header",
        citations=[{"chunk_id": "chunk-1", "document_id": "doc-1"}],
        metrics={"must_recall_passed": True, "must_recall_status": "passed"},
        retrieval_trace=None,
    )
    run_json = _write_run_json(
        tmp_path,
        {
            "items": [
                {
                    "meta": {
                        "must_recall_passed": True,
                        "provenance_integrity_passed": False,
                        "provenance_integrity_status": "failed",
                        "evidence_capsule": capsule,
                    }
                }
            ]
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is False
    assert result["summary"]["provenance_integrity_rate"] == 0.0
    assert "provenance_integrity_rate_below_threshold" in result["failures"]


def test_run_gate_strict_provenance_validates_capsule_from_item_meta(tmp_path: Path) -> None:
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule

    mod = _load_module()
    capsule = build_evidence_capsule(
        query_for_retrieval="retry header",
        citations=[{"chunk_id": "chunk-1", "document_id": "doc-1"}],
        metrics={"must_recall_passed": True, "must_recall_status": "passed"},
        retrieval_trace=None,
    )
    run_json = _write_run_json(
        tmp_path,
        {
            "items": [
                {
                    "meta": {
                        "must_recall_passed": True,
                        "provenance_integrity_passed": True,
                        "evidence_capsule": capsule,
                    }
                }
            ]
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
        strict_integrity=True,
    )

    assert result["passed"] is True
    assert result["summary"]["provenance_integrity_rate"] == 1.0


def test_run_gate_rejects_zero_case_passing_summary(tmp_path: Path) -> None:
    mod = _load_module()
    run_json = _write_run_json(
        tmp_path,
        {
            "run": {
                "summary": {
                    "must_recall_pass_rate": 1.0,
                    "must_recall_passed_cases": 0,
                    "must_recall_cases_total": 0,
                    "provenance_integrity_rate": 1.0,
                    "provenance_passed_cases": 0,
                    "provenance_cases_total": 0,
                }
            },
            "items": [],
        },
    )

    result = mod.run_gate(  # type: ignore[attr-defined]
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
    )

    assert result["passed"] is False
    assert "missing_must_recall_pass_rate" in result["failures"]
    assert "missing_provenance_integrity_rate" in result["failures"]
