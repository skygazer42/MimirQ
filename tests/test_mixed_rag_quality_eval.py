from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path("scripts/evaluate_mixed_rag_quality.py")
    spec = importlib.util.spec_from_file_location("evaluate_mixed_rag_quality", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_mixed_rag_eval_scores_complex_subquestions_without_llm_judge() -> None:
    mod = _load_module()
    cases = [
        {
            "id": "mixed-access-card",
            "question": "For an Alpha Desk access card replacement, where do I go, what do I bring, and who do I call?",
            "subquestions": [
                {"id": "service", "required_terms": ["access card replacement"]},
                {"id": "location", "required_terms": ["HQ Service Center"]},
                {"id": "material", "required_terms": ["employee badge"]},
                {"id": "phone", "required_terms": ["555-0100"]},
            ],
            "evidence_clauses": [
                {"id": "service", "required_terms": ["Service: access card replacement"]},
                {"id": "location", "required_terms": ["Location: HQ Service Center"]},
                {"id": "material", "required_terms": ["Required item: employee badge"]},
                {"id": "phone", "required_terms": ["Contact: 555-0100"]},
            ],
            "min_evidence_coverage": 1.0,
            "min_subquestion_coverage": 1.0,
            "max_wrong_evidence_rate": 0.25,
        }
    ]
    runs = [
        {
            "system": "mimirq-external",
            "items": [
                {
                    "case_id": "mixed-access-card",
                    "answer": "Use the HQ Service Center, bring an employee badge, and call 555-0100.",
                    "records": [
                        {
                            "title": "Access card runbook",
                            "content": (
                                "Service: access card replacement\n"
                                "Location: HQ Service Center\n"
                                "Required item: employee badge\n"
                                "Contact: 555-0100"
                            ),
                            "score": 0.93,
                        }
                    ],
                    "latency_ms": 820,
                }
            ],
        },
        {
            "system": "dify-native",
            "items": [
                {
                    "case_id": "mixed-access-card",
                    "answer": "Access card replacement is available at the HQ Service Center.",
                    "records": [
                        {
                            "title": "Access card runbook",
                            "content": "Service: access card replacement\nLocation: HQ Service Center",
                            "score": 0.81,
                        },
                        {
                            "title": "Unrelated payroll note",
                            "content": "Payroll reimbursement timing is published every Friday.",
                            "score": 0.61,
                        },
                    ],
                    "latency_ms": 620,
                }
            ],
        },
    ]

    report = mod.evaluate_mixed_rag_quality(cases=cases, runs=runs)

    by_system = {row["system"]: row for row in report["systems"]}
    assert by_system["mimirq-external"]["mean_evidence_coverage"] == 1.0
    assert by_system["mimirq-external"]["mean_subquestion_coverage"] == 1.0
    assert by_system["mimirq-external"]["retrieval_pass_rate"] == 1.0
    assert by_system["dify-native"]["mean_evidence_coverage"] == 0.5
    assert by_system["dify-native"]["mean_subquestion_coverage"] == 0.5
    assert by_system["dify-native"]["mean_wrong_evidence_rate"] == 0.5
    assert report["leaderboard"][0]["system"] == "mimirq-external"
    assert report["method"]["judge"] == "deterministic_term_and_metadata_matching"


def test_mixed_rag_eval_flags_answer_facts_not_supported_by_retrieval() -> None:
    mod = _load_module()
    case = {
        "id": "mixed-device-refresh",
        "question": "What is the entry point, request window, and eligible refresh type for device replacement?",
        "subquestions": [
            {"id": "entry", "required_terms": ["Service Portal"]},
            {"id": "date", "required_terms": ["January 1 to December 31, 2025"]},
            {"id": "type", "required_terms": ["standard refresh", "break-fix refresh"]},
        ],
        "evidence_clauses": [
            {"id": "entry", "required_terms": ["Service Portal"]},
            {"id": "date", "required_terms": ["January 1 to December 31, 2025"]},
            {"id": "type", "required_terms": ["standard refresh", "break-fix refresh"]},
        ],
    }
    run = {
        "system": "workflow-answer-only",
        "items": [
            {
                "case_id": "mixed-device-refresh",
                "answer": (
                    "Submit through the Service Portal during January 1 to December 31, 2025; "
                    "eligible types include standard refresh and break-fix refresh."
                ),
                "records": [
                    {
                        "title": "Device refresh entry",
                        "content": "Device replacement requests are submitted through the Service Portal.",
                    }
                ],
            }
        ],
    }

    report = mod.evaluate_mixed_rag_quality(cases=[case], runs=[run])
    item = report["items"][0]

    assert item["answer_clause_coverage"] == 1.0
    assert item["evidence_coverage"] == pytest.approx(1 / 3)
    assert item["answer_supported_clause_rate"] == pytest.approx(1 / 3)
    assert item["unsupported_answered_clause_ids"] == ["date", "type"]
    assert item["passed_retrieval"] is False


def test_mixed_rag_eval_uses_case_answer_term_aliases_without_relaxing_evidence() -> None:
    mod = _load_module()
    case = {
        "id": "mixed-contact",
        "question": "Who do I call for device support?",
        "subquestions": [{"id": "phone", "required_clause_ids": ["phone"]}],
        "evidence_clauses": [{"id": "phone", "required_terms": ["Contact:", "555-0100"]}],
        "answer_term_aliases": {"Contact:": ["Phone:", "Contact phone:"]},
    }
    run = {
        "system": "workflow-answer",
        "items": [
            {
                "case_id": "mixed-contact",
                "answer": "Phone: 555-0100.",
                "records": [{"content": "Contact: 555-0100"}],
            }
        ],
    }

    report = mod.evaluate_mixed_rag_quality(cases=[case], runs=[run])
    item = report["items"][0]

    assert item["evidence_coverage"] == 1.0
    assert item["answer_clause_coverage"] == 1.0
    assert item["answer_subquestion_coverage"] == 1.0


def test_mixed_rag_eval_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    run_path = tmp_path / "mimirq.json"
    out_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    cases_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.mixed_rag_eval_cases.v1",
                "cases": [
                    {
                        "id": "case-1",
                        "question": "Where do I replace an access card?",
                        "subquestions": [{"id": "location", "required_terms": ["HQ Service Center"]}],
                        "evidence_clauses": [{"id": "location", "required_terms": ["HQ Service Center"]}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.mixed_rag_eval_run.v1",
                "system": "mimirq",
                "items": [
                    {
                        "case_id": "case-1",
                        "answer": "Use the HQ Service Center.",
                        "records": [{"title": "Access card runbook", "content": "Location: HQ Service Center"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--cases",
            str(cases_path),
            "--run",
            f"mimirq={run_path}",
            "--out",
            str(out_path),
            "--out-md",
            str(md_path),
            "--min-mean-evidence-coverage",
            "0.9",
        ]
    )

    assert rc == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert report["schema"] == "mimirq.mixed_rag_quality_report.v1"
    assert report["gate"]["passed"] is True
    assert "| mimirq | 1 | 1.000 | 1.000 |" in markdown
