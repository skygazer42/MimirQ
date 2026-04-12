from __future__ import annotations

import json
import sys


def test_release_gate_render_markdown_mentions_parsing_proof_sections() -> None:
    import scripts.release_gate as mod

    markdown = mod._render_markdown(  # noqa: SLF001
        {
            "passed": True,
            "queryset_health": {"policy": "warn", "path": "artifacts/queryset_health.snapshot.json", "observed": {}},
            "queryset_health_hybrid": {"policy": "warn", "path": "artifacts/queryset_health.snapshot.hybrid.json", "observed": {}},
            "queryset_health_diff": {"policy": "fail", "path": "artifacts/queryset_health.diff.json", "observed": {}},
            "queryset_health_diff_hybrid": {"policy": "fail", "path": "artifacts/queryset_health.diff.hybrid.json", "observed": {}},
            "parsing_proof": {
                "policy": "warn",
                "path": "artifacts/parsing_proof_broader_sample/summary.json",
                "observed": {"cases_total": 2, "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_count": 1},
                "details": {"failed_case_ids": ["case-a"]},
            },
            "parsing_proof_diff": {
                "policy": "warn",
                "path": "artifacts/parsing_proof_broader_sample/diff.json",
                "observed": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0},
                "details": {"failed_case_added_ids": ["case-a"], "failed_case_removed_ids": []},
            },
            "retrieval_leaderboard": {"policy": "warn", "path": "", "observed": {}},
            "notes": [],
            "violations": [],
        }
    )

    assert "## parsing_proof" in markdown
    assert "artifacts/parsing_proof_broader_sample/summary.json" in markdown
    assert "Summary: `cases_total=2` `hit_at_k_mean=1.0` `mrr_mean=1.0`" in markdown
    assert "Failed cases: `1`" in markdown
    assert "Failed case IDs: `case-a`" in markdown
    assert "## parsing_proof_diff" in markdown
    assert "artifacts/parsing_proof_broader_sample/diff.json" in markdown
    assert "Delta summary: `hit_at_k_mean_delta=0.0` `mrr_mean_delta=0.0` `failed_case_added_count=1`" in markdown
    assert "Added failed cases: `case-a`" in markdown


def test_release_gate_render_markdown_highlights_clean_parsing_proof_sections() -> None:
    import scripts.release_gate as mod

    markdown = mod._render_markdown(  # noqa: SLF001
        {
            "passed": True,
            "parsing_proof": {
                "policy": "warn",
                "path": "artifacts/parsing_proof_broader_sample/summary.json",
                "observed": {"cases_total": 11, "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_count": 0},
                "details": {"failed_case_ids": []},
            },
            "parsing_proof_diff": {
                "policy": "warn",
                "path": "artifacts/parsing_proof_broader_sample/diff.json",
                "observed": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0, "failed_case_added_count": 0},
                "details": {"failed_case_added_ids": [], "failed_case_removed_ids": []},
            },
            "notes": [],
            "violations": [],
        }
    )

    assert "Failed case IDs: `none`" in markdown
    assert "Callout: `no parsing-proof failures in current sample`" in markdown
    assert "Added failed cases: `none`" in markdown
    assert "Callout: `no negative parsing-proof drift vs baseline`" in markdown


def test_release_gate_main_writes_markdown_report(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    import scripts.release_gate as mod

    budgets = tmp_path / "budgets.json"
    summary = tmp_path / "summary.json"
    diff = tmp_path / "diff.json"
    out = tmp_path / "release_gate.report.json"
    out_md = tmp_path / "release_gate.report.md"

    budgets.write_text(
        json.dumps(
            {
                "schema": "mimirq.release_gate_budgets.v1",
                "parsing_proof": {
                    "path": str(summary),
                    "policy": "warn",
                    "thresholds": {"hit_at_k_mean": {"min": 1.0}, "mrr_mean": {"min": 1.0}, "failed_case_count": {"max": 0}},
                },
                "parsing_proof_diff": {
                    "path": str(diff),
                    "policy": "warn",
                    "thresholds": {"hit_at_k_mean_delta": {"min": 0.0}, "mrr_mean_delta": {"min": 0.0}, "failed_case_added_count": {"max": 0}},
                },
            }
        ),
        encoding="utf-8",
    )
    summary.write_text(json.dumps({"hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []}), encoding="utf-8")
    diff.write_text(
        json.dumps({"metric_deltas": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0}, "failed_case_drift": {"added_ids": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_http_get_json", lambda *_a, **_k: {}, raising=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_gate.py",
            "--base-url",
            "http://example.test/api/v1",
            "--tenant-id",
            "t",
            "--user-id",
            "u",
            "--budgets",
            str(budgets),
            "--skip-regression",
            "--out-report",
            str(out),
            "--out-report-md",
            str(out_md),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]

    assert rc == 0
    assert out.exists()
    assert out_md.exists()
    assert "## parsing_proof" in out_md.read_text(encoding="utf-8")
