import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_readiness_status.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_readiness_status", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_format_status_prints_failed_root_cause_and_next_action() -> None:
    mod = _load_module()
    report = {
        "generated_at": "2026-06-06T23:56:19Z",
        "artifact_generated_at": {
            "knowledge_map": "2026-06-06T23:56:18Z",
            "console_auth": "2026-06-06T23:56:19Z",
        },
        "summary": {
            "passed": False,
            "root_cause_stage": "console_auth",
            "root_cause_reason": "token_expired",
            "next_action": "Refresh Dify console login with DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD_FILE, then run make dify-console-login.",
            "skipped_stages": ["external_probe", "full_gate"],
        },
        "artifacts": {"console_auth": "/tmp/dify_console_check.json"},
    }

    text = mod.format_status(report)

    assert "Changzhou Dify readiness: FAILED" in text
    assert "Generated at: 2026-06-06T23:56:19Z" in text
    assert "Root cause: console_auth (token_expired)" in text
    assert "Next action: Refresh Dify console login" in text
    assert "Skipped stages: external_probe, full_gate" in text
    assert "Artifact times: knowledge_map=2026-06-06T23:56:18Z; console_auth=2026-06-06T23:56:19Z" in text
    assert "console_auth=/tmp/dify_console_check.json" in text


def test_format_status_prints_passed_summary() -> None:
    mod = _load_module()
    report = {
        "summary": {"passed": True, "failed_stages": [], "skipped_stages": []},
        "artifacts": {"readiness": "/tmp/readiness.json"},
    }

    text = mod.format_status(report)

    assert text.splitlines()[0] == "Changzhou Dify readiness: PASSED"
    assert "Root cause:" not in text


def test_main_returns_nonzero_for_failed_summary(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    mod = _load_module()
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps({"summary": {"passed": False, "root_cause_stage": "console_auth"}}), encoding="utf-8")

    rc = mod.main(["--summary", str(path)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Changzhou Dify readiness: FAILED" in captured.out
