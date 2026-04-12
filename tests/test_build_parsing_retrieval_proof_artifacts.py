from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "build_parsing_retrieval_proof_artifacts.py"
    spec = importlib.util.spec_from_file_location("build_parsing_retrieval_proof_artifacts", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_parsing_proof_summary_uses_batch_metrics() -> None:
    mod = _load_script()
    payload = mod.build_parsing_proof_summary(  # type: ignore[attr-defined]
        {
            "cases_total": 4,
            "query_count_total": 8,
            "case_family_counts": {"specialty": 2, "table": 1, "layout": 1},
            "case_category_counts": {"chart": 1, "qr": 1, "cross_page_table_pdf": 1, "two_column_pdf": 1},
            "summary": {"hit_at_k_mean": 0.75, "mrr_mean": 0.625},
            "cases": [
                {"id": "chart_pdf_case", "summary": {"hit_at_k": 1.0, "mrr": 1.0}},
                {"id": "qr_image_case", "summary": {"hit_at_k": 1.0, "mrr": 0.5}},
                {"id": "cross_page_table_pdf_case", "summary": {"hit_at_k": 0.0, "mrr": 0.0}},
                {"id": "two_column_pdf_case", "summary": {"hit_at_k": 1.0, "mrr": 1.0}},
            ],
        }
    )
    assert payload["schema"] == "mimirq.parsing_retrieval_proof_summary.v1"
    assert payload["cases_total"] == 4
    assert payload["query_count_total"] == 8
    assert payload["hit_at_k_mean"] == 0.75
    assert payload["mrr_mean"] == 0.625
    assert payload["failed_case_ids"] == ["qr_image_case", "cross_page_table_pdf_case"]
    assert payload["sample_composition"] == {
        "case_family_counts": {"specialty": 2, "table": 1, "layout": 1},
        "case_category_counts": {"chart": 1, "qr": 1, "cross_page_table_pdf": 1, "two_column_pdf": 1},
    }
    assert payload["category_summaries"] == [
        {
            "name": "image",
            "cases_total": 2,
            "case_ids": ["chart_pdf_case", "qr_image_case"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 0.75,
            "failed_case_ids": ["qr_image_case"],
        },
        {
            "name": "layout",
            "cases_total": 1,
            "case_ids": ["two_column_pdf_case"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
        },
        {
            "name": "table",
            "cases_total": 1,
            "case_ids": ["cross_page_table_pdf_case"],
            "hit_at_k_mean": 0.0,
            "mrr_mean": 0.0,
            "failed_case_ids": ["cross_page_table_pdf_case"],
        },
    ]
    assert payload["slice_summaries"] == [
        {
            "name": "chart",
            "cases_total": 1,
            "case_ids": ["chart_pdf_case"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
        },
        {
            "name": "cross_page_table",
            "cases_total": 1,
            "case_ids": ["cross_page_table_pdf_case"],
            "hit_at_k_mean": 0.0,
            "mrr_mean": 0.0,
            "failed_case_ids": ["cross_page_table_pdf_case"],
        },
        {
            "name": "qr",
            "cases_total": 1,
            "case_ids": ["qr_image_case"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 0.5,
            "failed_case_ids": ["qr_image_case"],
        },
        {
            "name": "two_column",
            "cases_total": 1,
            "case_ids": ["two_column_pdf_case"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
        },
    ]


def test_build_parsing_proof_report_uses_threshold_checks() -> None:
    mod = _load_script()
    report = mod.build_parsing_proof_report(  # type: ignore[attr-defined]
        {
            "hit_at_k_mean": 1.0,
            "mrr_mean": 0.75,
            "failed_case_ids": ["case-b"],
            "query_count_total": 2,
            "sample_composition": {
                "case_family_counts": {"specialty": 1},
                "case_category_counts": {"chart": 1},
            },
            "category_summaries": [
                {"name": "image", "cases_total": 1, "case_ids": ["chart_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.75, "failed_case_ids": ["case-b"]}
            ],
            "slice_summaries": [
                {"name": "chart", "cases_total": 1, "case_ids": ["chart_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.75, "failed_case_ids": ["case-b"]}
            ],
        },
        summary_path="artifacts/parsing_proof.summary.json",
        thresholds={"hit_at_k_mean": 1.0, "mrr_mean": 0.8},
        rollout={
            "schema": "mimirq.parsing_retrieval_proof_rollout.v1",
            "current_stage": "informational",
            "allowed_stages": ["informational", "warn", "fail"],
            "promotion_requirements": {
                "informational_to_warn": ["stable_sample_corpus", "low_noise_history"],
                "warn_to_fail": ["stable_sample_corpus", "release_surface_reviewable"],
            },
            "owner_roles": ["parsing", "retrieval", "release-quality"],
        },
    )
    assert report["schema"] == "mimirq.parsing_retrieval_proof_report.v1"
    assert report["summary_path"] == "artifacts/parsing_proof.summary.json"
    assert report["checks"]["hit_at_k_mean"]["passed"] is True
    assert report["checks"]["mrr_mean"]["passed"] is False
    assert report["failed_case_ids"] == ["case-b"]
    assert report["category_summaries"] == [
        {"name": "image", "cases_total": 1, "case_ids": ["chart_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.75, "failed_case_ids": ["case-b"]}
    ]
    assert report["slice_summaries"] == [
        {"name": "chart", "cases_total": 1, "case_ids": ["chart_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.75, "failed_case_ids": ["case-b"]}
    ]
    assert report["query_count_total"] == 2
    assert report["sample_composition"] == {
        "case_family_counts": {"specialty": 1},
        "case_category_counts": {"chart": 1},
    }
    assert report["rollout"] == {
        "schema": "mimirq.parsing_retrieval_proof_rollout.v1",
        "current_stage": "informational",
        "next_stage": "warn",
        "owner_roles": ["parsing", "retrieval", "release-quality"],
        "promotion_requirements": ["stable_sample_corpus", "low_noise_history"],
    }
    assert report["passed"] is False


def test_parsing_proof_artifacts_builder_main_writes_relative_summary_path(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    batch_path = tmp_path / "batch.report.json"
    batch_path.write_text(
        json.dumps(
            {
                "cases_total": 1,
                "query_count_total": 2,
                "case_family_counts": {"document": 1},
                "case_category_counts": {"other": 1},
                "summary": {"hit_at_k_mean": 1.0, "mrr_mean": 1.0},
                "cases": [{"id": "case-a", "summary": {"hit_at_k": 1.0, "mrr": 1.0}}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--batch-report",
            str(batch_path),
            "--summary-out",
            "artifacts/parsing_proof.summary.json",
            "--report-out",
            "artifacts/parsing_proof.report.json",
        ]
    )

    assert rc == 0
    summary = json.loads((tmp_path / "artifacts" / "parsing_proof.summary.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "artifacts" / "parsing_proof.report.json").read_text(encoding="utf-8"))
    assert summary["query_count_total"] == 2
    assert summary["sample_composition"] == {
        "case_family_counts": {"document": 1},
        "case_category_counts": {"other": 1},
    }
    assert summary["category_summaries"] == [
        {
            "name": "other",
            "cases_total": 1,
            "case_ids": ["case-a"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
        }
    ]
    assert summary["slice_summaries"] == [
        {
            "name": "other",
            "cases_total": 1,
            "case_ids": ["case-a"],
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
        }
    ]
    assert report["summary_path"] == "artifacts/parsing_proof.summary.json"
    assert report["query_count_total"] == 2
