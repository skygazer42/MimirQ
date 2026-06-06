from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_trace_report.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_trace_report", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_load_console_token_prefers_explicit_then_storage_state(tmp_path: Path) -> None:
    mod = _load_module()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "origins": [
                    {
                        "origin": "https://dify.example.com:3000",
                        "localStorage": [{"name": "console_token", "value": "stored-console-token"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert mod.load_console_token("explicit-token", str(state_path), env={}) == "explicit-token"
    assert mod.load_console_token("", str(state_path), env={}) == "stored-console-token"
    assert mod.load_console_token("", "", env={"DIFY_CONSOLE_TOKEN": "env-token"}) == "env-token"


def test_collect_trace_report_fetches_message_and_node_executions_without_leaking_token() -> None:
    mod = _load_module()
    calls: list[str] = []

    def fake_request_json(*, console_base_url: str, console_token: str, path: str, timeout: float) -> dict:
        calls.append(path)
        assert console_base_url == "https://dify.test/console/api"
        assert console_token == "secret-console-token"
        assert timeout == 12.0
        if path.endswith("/messages/msg-1"):
            return {
                "workflow_run_id": "run-1",
                "answer": "您好，“小畅”只能答复常州市政务服务领域的相关知识，例如事项或业务办理，超出领域的问题小畅暂时无法回答，您可以尝试更改描述！",
            }
        if path.endswith("/workflow-runs/run-1/node-executions"):
            return {
                "data": [
                    {
                        "index": 3,
                        "title": "兜底回复",
                        "node_type": "answer",
                        "outputs": {"answer": "您好，“小畅”只能答复常州市政务服务领域的相关知识，例如事项或业务办理，超出领域的问题小畅暂时无法回答，您可以尝试更改描述！"},
                    },
                    {
                        "index": 2,
                        "title": "判断是否为空",
                        "node_type": "if-else",
                        "outputs": {"result": False},
                    },
                    {
                        "index": 1,
                        "title": "新北区政务服务知识检索",
                        "node_type": "knowledge-retrieval",
                        "inputs": {"query": "新北区社保卡补卡在哪里办理"},
                        "outputs": {"result": []},
                    },
                    {
                        "index": 0,
                        "title": "区域提取器",
                        "node_type": "parameter-extractor",
                        "outputs": {"region": "未知"},
                    },
                ]
            }
        raise AssertionError(path)

    report = mod.collect_trace_report(
        answers=[
            {
                "id": "case-1",
                "query": "新北区社保卡补卡在哪里办理",
                "message_id": "msg-1",
                "answer": "您好，“小畅”只能答复常州市政务服务领域的相关知识，例如事项或业务办理，超出领域的问题小畅暂时无法回答，您可以尝试更改描述！",
            }
        ],
        app_id="app-1",
        console_base_url="https://dify.test/console/api",
        console_token="secret-console-token",
        request_json=fake_request_json,
        timeout=12.0,
    )

    text = json.dumps(report, ensure_ascii=False)
    assert "secret-console-token" not in text
    assert calls == ["/apps/app-1/messages/msg-1", "/apps/app-1/workflow-runs/run-1/node-executions"]
    assert report["summary"] == {
        "cases": 1,
        "traced": 1,
        "fallback_cases": 1,
        "empty_retrieval_cases": 1,
        "nonempty_retrieval_cases": 0,
        "trace_errors": 0,
    }
    assert report["cases"][0]["workflow_run_id"] == "run-1"
    assert report["cases"][0]["answer_node_title"] == "兜底回复"
    assert report["cases"][0]["regions"] == ["未知"]
    assert report["cases"][0]["retrievals"] == [
        {"title": "新北区政务服务知识检索", "query": "新北区社保卡补卡在哪里办理", "count": 0}
    ]


def test_collect_trace_report_handles_answer_without_message_id() -> None:
    mod = _load_module()

    report = mod.collect_trace_report(
        answers=[{"id": "case-1", "query": "q", "answer": "a"}],
        app_id="app-1",
        console_base_url="https://dify.test/console/api",
        console_token="secret-console-token",
        request_json=lambda **_kwargs: {},
        timeout=12.0,
    )

    assert report["summary"]["trace_errors"] == 1
    assert report["cases"][0]["error"] == "missing message_id"
