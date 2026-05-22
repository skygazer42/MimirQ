from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_module():
    path = _repo_root() / "scripts" / "rag_pipeline_quality_suite.py"
    spec = importlib.util.spec_from_file_location("rag_pipeline_quality_suite", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_suite_dry_run_prints_plan(capsys) -> None:  # noqa: ANN001
    mod = _load_module()

    rc = mod.main(["--profile", "smoke", "--base-url", "http://api:8000"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "mimirq.rag_pipeline_quality_suite.plan.v1" in captured.out
    assert "production_readiness_chain" in captured.out
    assert "--llm-probe-timeout" in captured.out


def test_suite_builds_server_profile_and_skips_optional_gates() -> None:
    mod = _load_module()
    args = mod.parse_args(
        [
            "--profile",
            "server",
            "--base-url",
            "http://api:8000",
            "--tenant-id",
            "tenant",
            "--user-id",
            "user",
            "--max-retrieve-p95-ms",
            "1500",
        ]
    )

    phases = mod.build_phases(args)
    by_name = {phase.name: phase for phase in phases}

    load_cmd = by_name["rag_e2e_load_test"].command
    assert "--ingest-count" in load_cmd
    assert load_cmd[load_cmd.index("--ingest-count") + 1] == "20"
    assert load_cmd[load_cmd.index("--max-retrieve-p95-ms") + 1] == "1500"
    assert by_name["live_parser_matrix"].required is False
    assert by_name["kg_regression_gate"].skip_reason
    assert by_name["answer_quality_gate"].skip_reason


def test_suite_accepts_live_parser_matrix() -> None:
    mod = _load_module()
    args = mod.parse_args(
        [
            "--parser-fixture",
            "sample.pdf",
            "--parser-backends",
            "basic,mineru",
        ]
    )

    phases = mod.build_phases(args)
    parser_phase = {phase.name: phase for phase in phases}["live_parser_matrix"]

    assert parser_phase.required is True
    assert "--live-parser-backends" in parser_phase.command
    assert "basic,mineru" in parser_phase.command
