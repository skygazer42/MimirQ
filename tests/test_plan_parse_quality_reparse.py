from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_plan_parse_quality_reparse_writes_candidates(tmp_path: Path) -> None:
    mod = _load_script("scripts/plan_parse_quality_reparse.py")
    report = tmp_path / "report.json"
    out = tmp_path / "plan.json"
    report.write_text(
        json.dumps(
            {
                "dataset_id": "d-1",
                "parse_risk_summary": {
                    "low_threshold": 0.35,
                    "recommendation": "high_parse_risk_reparse_documents",
                    "considered_documents": 5,
                    "high_risk_documents": 3,
                    "top_low_quality_documents": [
                        {"document_id": "doc-c", "score": 0.3},
                        {"document_id": "doc-a", "score": 0.1},
                        {"document_id": "doc-b", "score": 0.2},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--report", str(report), "--out", str(out), "--max-docs", "2"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.parse_quality_reparse_plan.v1"
    assert payload.get("dataset_id") == "d-1"
    candidates = payload.get("candidates") or []
    assert [c.get("document_id") for c in candidates] == ["doc-a", "doc-b"]
    assert [c.get("score") for c in candidates] == [0.1, 0.2]


def test_plan_parse_quality_reparse_respects_score_cutoff(tmp_path: Path) -> None:
    mod = _load_script("scripts/plan_parse_quality_reparse.py")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dataset_id": "d-2",
                "parse_risk_summary": {
                    "low_threshold": 0.35,
                    "top_low_quality_documents": [
                        {"document_id": "doc-a", "score": 0.1},
                        {"document_id": "doc-b", "score": 0.3},
                        {"document_id": "doc-c", "score": 0.4},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = mod.run(report_path=report, out=None, max_docs=10, max_score=0.25)
    candidates = payload.get("candidates") or []
    assert [c.get("document_id") for c in candidates] == ["doc-a"]


def test_plan_parse_quality_reparse_preserves_specialty_reasons(tmp_path: Path) -> None:
    mod = _load_script("scripts/plan_parse_quality_reparse.py")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dataset_id": "d-3",
                "parse_risk_summary": {
                    "low_threshold": 0.35,
                    "top_low_quality_documents": [
                        {
                            "document_id": "doc-seal",
                            "score": 0.22,
                            "reason": "seal_low_confidence",
                            "specialty_signals": {
                                "seal_confidence": 0.22,
                                "seal_expected": True,
                            },
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = mod.run(report_path=report, out=None, max_docs=10, max_score=None)
    candidates = payload.get("candidates") or []
    assert candidates[0]["document_id"] == "doc-seal"
    assert candidates[0]["reason"] == "seal_low_confidence"
    assert candidates[0]["specialty_signals"]["seal_confidence"] == 0.22
