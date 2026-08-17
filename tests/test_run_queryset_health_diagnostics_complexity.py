import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from app.services import queryset_health_service
from scripts import run_queryset_health_diagnostics as diagnostics


def test_resolve_profile_hash_prefers_explicit_then_benchmark() -> None:
    args = argparse.Namespace(profile_hash=" explicit ", profile_json=None)
    assert diagnostics._resolve_profile_hash(args=args, benchmark={"profile_hash": "benchmark"}) == "explicit"

    args.profile_hash = ""
    assert diagnostics._resolve_profile_hash(args=args, benchmark={"profile_hash": " benchmark "}) == "benchmark"


def test_run_merges_policy_tracks_history_and_emits_cron_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    policy_path = tmp_path / "policy.json"
    history_path = tmp_path / "history.jsonl"
    output_path = tmp_path / "reports" / "health.json"
    benchmark_path.write_text('{"profile_hash": "profile-1"}', encoding="utf-8")
    policy_path.write_text('{"hard_cases_limit": 8}', encoding="utf-8")
    calls: dict[str, Any] = {}
    snapshot = {
        "schema": "mimirq.queryset_health.v1",
        "status": "warn",
        "degradation_flags": ["miss_rate"],
        "profile_hash": "profile-1",
        "policy_source": "policy_json+cli_overrides",
        "policy_hash": "policy-hash",
        "trend": {"policy_changed": True},
        "risk": {
            "miss_rate": 0.2,
            "weak_hit_rate": 0.1,
            "hard_cases": [{"id": "case-a"}, "invalid", {"id": "case-c"}, {"id": "case-d"}],
        },
    }

    def build_queryset_health_snapshot(**kwargs: Any) -> dict[str, Any]:
        calls["build"] = kwargs
        return snapshot

    def update_queryset_health_history(**kwargs: Any) -> list[dict[str, Any]]:
        calls["update"] = kwargs
        return [snapshot]

    monkeypatch.setattr(queryset_health_service, "load_queryset_health_history", lambda _path: [{"id": "prev"}])
    monkeypatch.setattr(queryset_health_service, "build_queryset_health_snapshot", build_queryset_health_snapshot)
    monkeypatch.setattr(
        queryset_health_service,
        "update_queryset_health_history",
        update_queryset_health_history,
    )
    monkeypatch.setattr(
        queryset_health_service,
        "write_queryset_health_history",
        lambda path, rows: calls.setdefault("write", (path, rows)),
    )

    result = diagnostics.run(
        benchmark_report=benchmark_path,
        out=output_path,
        history=history_path,
        profile_hash=None,
        profile_json=None,
        policy_json=policy_path,
        miss_rate_regression_threshold=0.05,
        weak_hit_rate_regression_threshold=None,
        weak_hit_rr_threshold=0.3,
        hard_cases_limit=None,
        max_history=12,
        cron=True,
    )

    assert result == snapshot
    assert json.loads(output_path.read_text(encoding="utf-8")) == snapshot
    assert calls["build"] == {
        "benchmark_report": {"profile_hash": "profile-1"},
        "profile_hash": "profile-1",
        "previous_snapshot": {"id": "prev"},
        "policy": {
            "hard_cases_limit": 8,
            "miss_rate_regression_threshold": 0.05,
            "weak_hit_rr_threshold": 0.3,
        },
        "policy_source": "policy_json+cli_overrides",
    }
    assert calls["update"] == {"history": [{"id": "prev"}], "current": snapshot, "max_items": 12}
    assert calls["write"][0] == history_path
    summary = json.loads(capsys.readouterr().out)
    assert summary["hard_case_ids"] == ["case-a", "case-c"]
    assert summary["policy_changed"] is True
    assert summary["out"] == str(output_path)


def test_run_uses_default_policy_and_human_summary_without_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    output_path = tmp_path / "health.json"
    benchmark_path.write_text('{"profile_hash": "profile-2"}', encoding="utf-8")
    snapshot = {"status": "ok", "profile_hash": "profile-2"}
    calls: dict[str, Any] = {}

    def build_queryset_health_snapshot(**kwargs: Any) -> dict[str, Any]:
        calls.update(kwargs)
        return snapshot

    monkeypatch.setattr(queryset_health_service, "build_queryset_health_snapshot", build_queryset_health_snapshot)

    diagnostics.run(
        benchmark_report=benchmark_path,
        out=output_path,
        history=None,
        profile_hash=None,
        profile_json=None,
        policy_json=None,
        miss_rate_regression_threshold=None,
        weak_hit_rate_regression_threshold=None,
        weak_hit_rr_threshold=None,
        hard_cases_limit=None,
        max_history=90,
        cron=False,
    )

    assert calls["policy"] == {}
    assert calls["policy_source"] == "default"
    assert calls["previous_snapshot"] is None
    assert capsys.readouterr().out == (f"[queryset-health] status=ok out={output_path} profile_hash=profile-2\n")
