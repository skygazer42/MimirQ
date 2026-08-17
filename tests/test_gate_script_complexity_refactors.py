import json
import sys
from pathlib import Path

import pytest

from scripts import (
    answer_quality_gate,
    evidence_pack_to_regression_bundle,
    export_diagnostics,
    init_env,
    must_recall_provenance_gate,
    parsing_retrieval_proof_gate,
    validate_parsing_retrieval_proof_governance,
    verify_parse_repair_gate,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("module", "threshold_schema", "report_schema", "default_out", "prefix", "input_payload"),
    [
        (
            answer_quality_gate,
            "mimirq.answer_quality_thresholds.v1",
            "mimirq.answer_quality_gate_report.v1",
            "artifacts/answer_quality.gate.json",
            "answer-quality-gate",
            {"run": {"summary": {"score": "0.8", "ratio": 0.4}}},
        ),
        (
            parsing_retrieval_proof_gate,
            "mimirq.parsing_retrieval_proof_thresholds.v1",
            "mimirq.parsing_retrieval_proof_gate_report.v1",
            "artifacts/parsing_proof_broader_sample/gate.json",
            "parsing-proof-gate",
            {"summary": {"score": "0.8", "ratio": 0.4}},
        ),
    ],
)
def test_metric_gate_normalizes_thresholds_and_uses_default_output(
    module,
    threshold_schema: str,
    report_schema: str,
    default_out: str,
    prefix: str,
    input_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    normalized = module.normalize_thresholds(
        {
            "schema": threshold_schema,
            "metrics": {
                " score ": 0.75,
                "ratio": {"min": "0.1", "max": "0.9", "required": 0},
                "ignored": {"min": "bad", "max": "also-bad"},
                "skip": True,
                "": {"min": 1},
            },
        }
    )

    assert normalized == {
        "score": {"min": 0.75, "required": True},
        "ratio": {"min": 0.1, "max": 0.9, "required": False},
        "ignored": {"required": True},
    }

    with pytest.raises(ValueError, match="invalid_threshold_schema"):
        module.normalize_thresholds({"schema": "wrong.schema", "metrics": {}})

    input_path = _write_json(tmp_path / "summary.json", input_payload)
    thresholds_path = _write_json(
        tmp_path / "thresholds.json",
        {"schema": threshold_schema, "metrics": {"score": {"min": 0.7}, "ratio": {"max": 0.5}}},
    )
    monkeypatch.chdir(tmp_path)

    exit_code = module.main(["--input", str(input_path), "--thresholds", str(thresholds_path)])
    captured = capsys.readouterr()
    out_path = (tmp_path / default_out).resolve()
    report = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"[{prefix}] wrote {out_path}",
        f"[{prefix}] PASS",
    ]
    assert report["schema"] == report_schema
    assert report["passed"] is True
    assert report["input"] == str(input_path.resolve())
    assert report["thresholds"] == str(thresholds_path.resolve())
    assert [row["metric"] for row in report["checks"]] == ["score", "ratio"]


@pytest.mark.parametrize("module", [answer_quality_gate, parsing_retrieval_proof_gate])
def test_metric_gate_returns_failure_exit_and_missing_file_system_exit(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = _write_json(tmp_path / "summary.json", {"summary": {}})
    thresholds_path = _write_json(tmp_path / "thresholds.json", {"metrics": {"score": {"min": 0.7}}})
    monkeypatch.chdir(tmp_path)

    exit_code = module.main(["--input", str(input_path), "--thresholds", str(thresholds_path)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    assert captured.out.splitlines()[-1].endswith("FAIL")

    with pytest.raises(SystemExit, match="input_not_found"):
        module.main(["--input", str(tmp_path / "missing.json"), "--thresholds", str(thresholds_path)])


def test_evidence_pack_conversion_prefers_explicit_sources_and_falls_back_to_citations() -> None:
    quote = "q" * 2105
    explicit_pack = {
        "dataset_id": "dataset-a",
        "query": "What happened?",
        "reference_sources": [
            {"document_id": "doc-2", "chunk_id": "chunk-2", "quote": "two", "label": "second"},
            {"document_id": "doc-1", "chunk_id": "chunk-1", "quote": quote, "page_number": "3"},
            {"document_id": "doc-1", "chunk_id": "chunk-1", "quote": "duplicate"},
            {"document_id": "doc-missing"},
        ],
    }

    explicit_bundle = evidence_pack_to_regression_bundle.convert_evidence_pack_to_regression_bundle(
        explicit_pack,
        tags=[" alpha ", "alpha", "", "beta"],
    )
    assert explicit_bundle == {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": "dataset-a",
        "items": [
            {
                "question": "What happened?",
                "expected_answer": None,
                "reference_sources": [
                    {
                        "document_id": "doc-2",
                        "chunk_id": "chunk-2",
                        "chunk_index": None,
                        "page_number": None,
                        "start_char": None,
                        "end_char": None,
                        "doc_pipeline_key": None,
                        "pipeline_hash": None,
                        "quote": "two",
                        "label": "second",
                    },
                    {
                        "document_id": "doc-1",
                        "chunk_id": "chunk-1",
                        "chunk_index": None,
                        "page_number": 3,
                        "start_char": None,
                        "end_char": None,
                        "doc_pipeline_key": None,
                        "pipeline_hash": None,
                        "quote": "q" * 2000,
                        "label": None,
                    },
                ],
                "tags": ["alpha", "beta"],
            }
        ],
    }

    fallback_bundle = evidence_pack_to_regression_bundle.convert_evidence_pack_to_regression_bundle(
        {
            "dataset_id": "dataset-a",
            "query": "Fallback",
            "selected_chunk_ids": ["chunk-2", "chunk-1", "chunk-1"],
            "citations": [
                {"document_id": "doc-1", "chunk_id": "chunk-1", "chunk_content": "one"},
                {"document_id": "doc-2", "chunk_id": "chunk-2", "chunk_content": "two"},
                {"document_id": "doc-3", "chunk_id": "chunk-3", "chunk_content": "skip"},
            ],
        }
    )

    assert fallback_bundle["items"][0]["tags"] == ["evidence_pack"]
    assert [row["chunk_id"] for row in fallback_bundle["items"][0]["reference_sources"]] == ["chunk-1", "chunk-2"]


def test_evidence_pack_cli_emits_stdout_and_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = _write_json(
        tmp_path / "pack.json",
        {
            "dataset_id": "dataset-a",
            "query": "What happened?",
            "selected_chunk_ids": ["chunk-1"],
            "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1", "chunk_content": "quote"}],
        },
    )

    exit_code = evidence_pack_to_regression_bundle.main(["--in", str(input_path), "--pretty"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out)["items"][0]["tags"] == ["evidence_pack"]

    out_path = tmp_path / "bundle.json"
    object_override_code = evidence_pack_to_regression_bundle.main(
        ["--in", str(input_path), "--question", "override", "--out", str(out_path)]
    )
    object_override = capsys.readouterr()

    assert object_override_code == 0
    assert object_override.out == ""
    assert object_override.err == ""
    assert json.loads(out_path.read_text(encoding="utf-8"))["items"][0]["question"] == "override"

    list_path = _write_json(tmp_path / "pack-list.json", [json.loads(input_path.read_text(encoding="utf-8"))])
    list_error_code = evidence_pack_to_regression_bundle.main(["--in", str(list_path), "--question", "override"])
    list_error = capsys.readouterr()

    assert list_error_code == 2
    assert list_error.out == ""
    assert "ERROR: question override is not supported for list input" in list_error.err


def test_export_diagnostics_summarizes_sorted_counts_and_jsonl_inputs(tmp_path: Path) -> None:
    first_metric = {
        "event": "rag_done",
        "route": "Search",
        "retrieval_mode": "Hybrid",
        "metrics": {"elapsed_sec": "1.5", "retrieval_elapsed_sec": "0.5"},
    }
    second_metric = {
        "event": "rag_done",
        "route": "Answer",
        "metrics": {"elapsed_sec": 0.5, "retrieval_elapsed_sec": "bad", "retrieval_mode": "Dense"},
    }
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(first_metric),
                json.dumps(second_metric),
                json.dumps({"event": "rag_trace"}),
                "",
            ]
        ),
        encoding="utf-8",
    )
    feedback_path = _write_json(
        tmp_path / "feedback.json",
        [
            {"rating": 2, "reason": "", "tags": ["zeta", "alpha"]},
            {"rating": "1", "reason": "because", "tags": ["alpha", ""]},
        ],
    )

    payload = export_diagnostics.export_diagnostics(
        metrics_rows=export_diagnostics._read_json_or_jsonl(metrics_path),
        feedback_rows=export_diagnostics._read_json_or_jsonl(feedback_path),
    )

    assert payload["schema"] == "mimirq.export_diagnostics.v1"
    assert payload["metrics"]["avg_elapsed_sec"] == 1.0
    assert payload["metrics"]["avg_retrieval_elapsed_sec"] == 0.5
    assert list(payload["metrics"]["retrieval_mode_counts"]) == ["dense", "hybrid"]
    assert list(payload["metrics"]["route_counts"]) == ["answer", "search"]
    assert list(payload["feedback"]["rating_counts"]) == ["1", "2"]
    assert list(payload["feedback"]["tag_counts"]) == ["alpha", "zeta"]
    assert payload["feedback"]["reason_present_count"] == 1

    out_path = tmp_path / "diagnostics.json"
    exit_code = export_diagnostics.main(
        ["--metrics-jsonl", str(metrics_path), "--feedback-json", str(feedback_path), "--out", str(out_path)]
    )
    assert exit_code == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == payload


def test_init_env_main_dry_run_and_secret_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "web").mkdir(parents=True)
    (repo_root / ".env.example").write_text("SECRET_KEY=\nEXISTING=keep\n", encoding="utf-8")
    (repo_root / "web" / ".env.local.example").write_text("MARKDOWN_IMAGE_PROXY_SECRET=\n", encoding="utf-8")
    monkeypatch.setattr(init_env, "__file__", str(repo_root / "scripts" / "init_env.py"))
    root_env = repo_root / ".env"
    root_env_example = repo_root / ".env.example"
    web_env = repo_root / "web" / ".env.local"
    web_env_example = repo_root / "web" / ".env.local.example"

    monkeypatch.setattr(sys, "argv", ["init_env.py", "--dry-run"])
    assert init_env.main() == 0
    dry_run = capsys.readouterr()
    assert dry_run.out.splitlines() == [
        f"[init-env] WRITE: {root_env.as_posix()} <= {root_env_example.as_posix()}",
        f"[init-env] WRITE: {web_env.as_posix()} <= {web_env_example.as_posix()}",
    ]
    assert not root_env.exists()

    tokens = iter(["secret-token", "proxy-token"])
    monkeypatch.setattr(init_env.secrets, "token_urlsafe", lambda _n: next(tokens))
    monkeypatch.setattr(sys, "argv", ["init_env.py"])
    assert init_env.main() == 0
    applied = capsys.readouterr()
    assert applied.out.splitlines() == [
        f"[init-env] WRITE: {root_env.as_posix()} <= {root_env_example.as_posix()}",
        f"[init-env] WRITE: {web_env.as_posix()} <= {web_env_example.as_posix()}",
        "[init-env] filled SECRET_KEY in .env",
        "[init-env] filled MARKDOWN_IMAGE_PROXY_SECRET in .env",
        "[init-env] filled MARKDOWN_IMAGE_PROXY_SECRET in web/.env.local",
    ]
    assert root_env.read_text(encoding="utf-8") == (
        "SECRET_KEY=secret-token\nEXISTING=keep\nMARKDOWN_IMAGE_PROXY_SECRET=proxy-token\n"
    )
    assert web_env.read_text(encoding="utf-8") == ("MARKDOWN_IMAGE_PROXY_SECRET=proxy-token\n")


def test_must_recall_gate_cli_writes_output_and_reports_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_json = _write_json(
        tmp_path / "run.json",
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
    out_path = tmp_path / "gate.json"

    exit_code = must_recall_provenance_gate.main(["--run-json", str(run_json), "--out", str(out_path), "--compact"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["schema"] == "mimirq.must_recall_provenance_gate.v1"
    assert json.loads(out_path.read_text(encoding="utf-8")) == stdout_payload

    error_code = must_recall_provenance_gate.main(["--run-json", str(tmp_path / "missing.json")])
    error = capsys.readouterr()
    assert error_code == 1
    assert error.out == ""
    assert "[must_recall_provenance_gate] ERROR:" in error.err


def test_validate_governance_normalizes_lists_and_cli_reports_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "inputs"
    base.mkdir()
    required_paths = {
        "baseline_summary_path": base / "baseline.json",
        "thresholds_path": base / "thresholds.json",
        "policy_doc_path": base / "policy.md",
        "workflow_doc_path": base / "workflow.md",
    }
    for path in required_paths.values():
        path.write_text("ok", encoding="utf-8")
    workflow_a = base / "a.yml"
    workflow_b = base / "b.yml"
    workflow_a.write_text("a", encoding="utf-8")
    workflow_b.write_text("b", encoding="utf-8")

    payload = {
        "schema": "mimirq.parsing_retrieval_proof_governance.v1",
        "mode": " WARN ",
        "owner_roles": [" analyst ", "", "reviewer"],
        "sample_runner": "python scripts/run_sample.py",
        "baseline_summary_path": str(required_paths["baseline_summary_path"]),
        "thresholds_path": str(required_paths["thresholds_path"]),
        "policy_doc_path": str(required_paths["policy_doc_path"]),
        "workflow_doc_path": str(required_paths["workflow_doc_path"]),
        "workflows": [str(workflow_b), str(workflow_a)],
        "promotion_requirements": [" gated ", "", "signed-off"],
    }

    normalized = validate_parsing_retrieval_proof_governance.validate_governance(payload)
    assert normalized["schema"] == "mimirq.parsing_retrieval_proof_governance.v1"
    assert normalized["mode"] == "warn"
    assert normalized["owner_roles"] == ["analyst", "reviewer"]
    assert normalized["workflows"] == [str(workflow_b), str(workflow_a)]
    assert normalized["promotion_requirements"] == ["gated", "signed-off"]

    governance_path = _write_json(tmp_path / "governance.json", payload)
    out_path = tmp_path / "normalized.json"
    exit_code = validate_parsing_retrieval_proof_governance.main(
        ["--governance", str(governance_path), "--out", str(out_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.strip() == f"[parsing-proof-governance] valid policy={governance_path}"
    assert json.loads(out_path.read_text(encoding="utf-8")) == normalized

    invalid_path = _write_json(tmp_path / "invalid-governance.json", {**payload, "mode": "broken"})
    invalid_code = validate_parsing_retrieval_proof_governance.main(["--governance", str(invalid_path)])
    invalid = capsys.readouterr()
    assert invalid_code == 1
    assert invalid.out == ""
    assert "[parsing-proof-governance] invalid governance: invalid_mode" in invalid.err


def test_validate_governance_preserves_padding_in_valid_path_fields(tmp_path: Path) -> None:
    path_fields = {
        "baseline_summary_path": tmp_path / "baseline.json",
        "thresholds_path": tmp_path / "thresholds.json",
        "policy_doc_path": tmp_path / "policy.md",
        "workflow_doc_path": tmp_path / "workflow.md",
    }
    for path in path_fields.values():
        path.write_text("ok", encoding="utf-8")

    padded_paths = {key: f"  {path}\t" for key, path in path_fields.items()}
    payload = {
        "schema": "mimirq.parsing_retrieval_proof_governance.v1",
        "mode": "warn",
        "owner_roles": ["reviewer"],
        "sample_runner": "python scripts/run_sample.py",
        **padded_paths,
        "workflows": [str(path_fields["workflow_doc_path"])],
        "promotion_requirements": ["signed-off"],
    }

    normalized = validate_parsing_retrieval_proof_governance.validate_governance(payload)

    assert {key: normalized[key] for key in padded_paths} == padded_paths


def test_parse_repair_gate_extracts_nested_tail_and_clamps_cli_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nested_payload = {
        "actions": [{"document_id": "doc-1"}, {"document_id": "doc-2"}],
        "parse_risk_summary": {
            "parse_risk_tail": [{"document_id": "doc-2"}, {"document_id": "doc-3"}],
            "top_low_quality_documents": [{"document_id": "doc-4"}],
        },
        "parse_risk_tail_drift": {
            "retained_document_ids": ["doc-4", "doc-5"],
            "added_document_ids": ["doc-6", "doc-1"],
        },
        "nested": [{"parse_risk_summary": {"parse_risk_tail": [{"document_id": "doc-7"}]}}],
    }
    assert verify_parse_repair_gate._extract_tail_from_payload(nested_payload) == {
        "doc-1",
        "doc-2",
        "doc-3",
        "doc-4",
        "doc-5",
        "doc-6",
        "doc-7",
    }

    monkeypatch.setattr(verify_parse_repair_gate, "_now_utc_iso", lambda: "2026-08-16T00:00:00+00:00")
    report = verify_parse_repair_gate.evaluate_parse_repair_gate(
        baseline_payload={"actions": [{"document_id": "doc-a"}, {"document_id": "doc-b"}]},
        current_payload={"actions": [{"document_id": "doc-b"}, {"document_id": "doc-c"}]},
        min_shrinkage=0.1,
        max_added_tail=0,
        max_current_tail=5,
    )
    assert report == {
        "schema": "mimirq.parse_repair_gate_report.v1",
        "generated_at": "2026-08-16T00:00:00+00:00",
        "policy": {"min_shrinkage": 0.1, "max_added_tail": 0, "max_current_tail": 5},
        "observed": {
            "baseline_tail_count": 2,
            "current_tail_count": 2,
            "shrinkage": 0.0,
            "added_tail_count": 1,
            "removed_tail_count": 1,
            "retained_tail_count": 1,
            "added_document_ids": ["doc-c"],
            "removed_document_ids": ["doc-a"],
        },
        "passed": False,
        "failures": [
            "shrinkage=0.0000 < min_shrinkage=0.1000",
            "added_tail=1 > max_added_tail=0",
        ],
    }

    baseline_path = _write_json(tmp_path / "baseline.json", {"actions": [{"document_id": "doc-a"}]})
    current_path = _write_json(tmp_path / "current.json", {"actions": [{"document_id": "doc-b"}]})
    monkeypatch.chdir(tmp_path)
    exit_code = verify_parse_repair_gate.main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--min-shrinkage",
            "5",
            "--max-added-tail",
            "-3",
        ]
    )
    captured = capsys.readouterr()
    out_path = (tmp_path / "artifacts/parse_repair_gate.report.json").resolve()
    out_payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"[verify-parse-repair-gate] wrote {out_path}",
        "[verify-parse-repair-gate] passed=False",
    ]
    assert out_payload["policy"] == {
        "min_shrinkage": 1.0,
        "max_added_tail": 0,
        "max_current_tail": -1,
    }
    assert any("shrinkage=0.0000 < min_shrinkage=1.0000" in item for item in out_payload["failures"])

    with pytest.raises(SystemExit, match="baseline_not_found"):
        verify_parse_repair_gate.main(["--baseline", str(tmp_path / "missing.json"), "--current", str(current_path)])
