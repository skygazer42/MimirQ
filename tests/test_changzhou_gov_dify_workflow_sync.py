from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path("scripts/changzhou_gov_dify_workflow_sync.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_workflow_sync", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _draft_workflow() -> dict:
    return {
        "id": "workflow-current",
        "hash": "current-draft-hash",
        "graph": {"nodes": [{"id": "old-node", "data": {"type": "start"}}], "edges": []},
        "features": {"file_upload": {"enabled": False}},
        "environment_variables": [{"name": "CURRENT_ENV", "value": "old"}],
        "conversation_variables": [{"name": "currentVar", "value": ""}],
    }


def _target_workflow(*, prompt_leak: bool = False) -> dict:
    prompt = "知识库内容中有常见问题QA知识相关内容，输出此部分内容" if prompt_leak else "请根据检索结果回答用户问题。"
    return {
        "id": "workflow-target",
        "hash": "stale-target-hash",
        "graph": {
            "nodes": [
                {
                    "id": "new-node",
                    "data": {
                        "type": "llm",
                        "title": "LLM综合回复",
                        "prompt_template": [{"role": "system", "text": prompt}],
                    },
                }
            ],
            "edges": [],
        },
        "features": {"file_upload": {"enabled": True}},
        "environment_variables": [{"name": "TARGET_ENV", "value": "new"}],
        "conversation_variables": [{"name": "targetVar", "value": ""}],
    }


def test_build_sync_payload_uses_target_workflow_and_current_hash() -> None:
    mod = _load_module()

    payload = mod.build_sync_payload(_draft_workflow(), _target_workflow())

    assert payload == {
        "graph": _target_workflow()["graph"],
        "features": _target_workflow()["features"],
        "hash": "current-draft-hash",
        "environment_variables": _target_workflow()["environment_variables"],
        "conversation_variables": _target_workflow()["conversation_variables"],
    }


def test_sync_workflow_draft_dry_run_writes_backup_and_payload_without_posting(tmp_path: Path) -> None:
    mod = _load_module()
    backup_path = tmp_path / "backup.json"
    payload_path = tmp_path / "payload.json"
    calls: list[dict] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        assert kwargs["console_base_url"] == "https://dify.test/console/api"
        assert kwargs["console_token"] == "secret-console-token"
        assert kwargs["timeout"] == 12.0
        assert kwargs["path"] == "/apps/app-1/workflows/draft"
        assert kwargs["method"] == "GET"
        assert "payload" not in kwargs or kwargs["payload"] is None
        return _draft_workflow()

    report = mod.sync_workflow_draft(
        app_id="app-1",
        target_workflow=_target_workflow(),
        console_base_url="https://dify.test/console/api",
        console_token="secret-console-token",
        request_json=fake_request_json,
        timeout=12.0,
        backup_out=backup_path,
        payload_out=payload_path,
        apply=False,
        generated_at="2026-06-07T00:00:00Z",
    )

    assert [call["method"] for call in calls] == ["GET"]
    assert json.loads(backup_path.read_text(encoding="utf-8")) == _draft_workflow()
    assert json.loads(payload_path.read_text(encoding="utf-8")) == mod.build_sync_payload(
        _draft_workflow(), _target_workflow()
    )
    assert report["schema"] == "mimirq.changzhou_gov_service_knowledge.dify_workflow_sync.v1"
    assert report["generated_at"] == "2026-06-07T00:00:00Z"
    assert report["app_id"] == "app-1"
    assert report["dry_run"] is True
    assert report["applied"] is False
    assert report["summary"] == {
        "current_prompt_template_leak_warnings": 0,
        "target_prompt_template_leak_warnings": 0,
        "posted": False,
        "verified_after_post": False,
    }


def test_sync_workflow_draft_apply_posts_payload_and_verifies_remote_draft(tmp_path: Path) -> None:
    mod = _load_module()
    calls: list[dict] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        assert kwargs["path"] == "/apps/app-1/workflows/draft"
        if kwargs["method"] == "GET":
            return _draft_workflow() if len(calls) == 1 else _target_workflow()
        if kwargs["method"] == "POST":
            assert kwargs["payload"] == mod.build_sync_payload(_draft_workflow(), _target_workflow())
            return {"result": "ok"}
        raise AssertionError(kwargs["method"])

    report = mod.sync_workflow_draft(
        app_id="app-1",
        target_workflow=_target_workflow(),
        console_base_url="https://dify.test/console/api",
        console_token="secret-console-token",
        request_json=fake_request_json,
        timeout=12.0,
        backup_out=tmp_path / "backup.json",
        payload_out=tmp_path / "payload.json",
        apply=True,
        generated_at="2026-06-07T00:00:00Z",
    )

    assert [call["method"] for call in calls] == ["GET", "POST", "GET"]
    assert report["dry_run"] is False
    assert report["applied"] is True
    assert report["summary"]["posted"] is True
    assert report["summary"]["verified_after_post"] is True
    assert report["post_response"] == {"result": "ok"}
    assert report["post_verify_lint"]["summary"].get("prompt_template_leak_warnings", 0) == 0


def test_sync_workflow_draft_refuses_apply_when_target_prompt_template_leaks(tmp_path: Path) -> None:
    mod = _load_module()
    calls: list[dict] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        assert kwargs["method"] == "GET"
        return _draft_workflow()

    with pytest.raises(ValueError, match="target workflow has prompt-template leaks"):
        mod.sync_workflow_draft(
            app_id="app-1",
            target_workflow=_target_workflow(prompt_leak=True),
            console_base_url="https://dify.test/console/api",
            console_token="secret-console-token",
            request_json=fake_request_json,
            timeout=12.0,
            backup_out=tmp_path / "backup.json",
            payload_out=tmp_path / "payload.json",
            apply=True,
        )

    assert [call["method"] for call in calls] == ["GET"]
