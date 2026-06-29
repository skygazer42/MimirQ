from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.error import URLError


def _load_module():
    path = Path("scripts/changzhou_gov_collect_dify_answers.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_collect_dify_answers", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_chat_payload_uses_query_without_workflow_mutation() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {"id": "case-1", "query": "新北区社保卡补卡在哪里办理"},
        mode="chat",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="query",
    )

    assert payload == {
        "inputs": {},
        "query": "新北区社保卡补卡在哪里办理",
        "response_mode": "blocking",
        "user": "golden-eval",
        "auto_generate_name": False,
    }


def test_build_chat_payload_passes_case_dify_inputs() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {
            "id": "case-1",
            "query": "新北区社保卡补卡在哪里办理",
            "dify_inputs": {"areaName": "新北区"},
        },
        mode="chat",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="query",
    )

    assert payload["inputs"] == {"areaName": "新北区"}
    assert payload["query"] == "新北区社保卡补卡在哪里办理"


def test_build_chat_payload_uses_top_level_area_name() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {
            "id": "case-1",
            "query": "申请表下载",
            "areaName": "常州市本级",
        },
        mode="chat",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="query",
    )

    assert payload["inputs"] == {"areaName": "常州市本级"}
    assert payload["query"] == "申请表下载"


def test_case_dify_inputs_prefers_explicit_dify_inputs_area_name() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {
            "id": "case-1",
            "query": "社保卡补办",
            "areaName": "常州市本级",
            "dify_inputs": {"areaName": "新北区"},
        },
        mode="chat",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="query",
    )

    assert payload["inputs"] == {"areaName": "新北区"}


def test_build_workflow_payload_places_query_in_inputs() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {"id": "case-1", "query": "汽车置换补贴怎么申请"},
        mode="workflow",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="question",
    )

    assert payload == {
        "inputs": {"question": "汽车置换补贴怎么申请"},
        "response_mode": "blocking",
        "user": "golden-eval",
    }


def test_build_workflow_payload_merges_case_dify_inputs_with_query_key() -> None:
    mod = _load_module()

    payload = mod.build_dify_payload(
        {
            "id": "case-1",
            "query": "汽车置换补贴怎么申请",
            "dify_inputs": {"areaName": "常州市本级"},
        },
        mode="workflow",
        user="golden-eval",
        response_mode="blocking",
        workflow_query_key="question",
    )

    assert payload == {
        "inputs": {"areaName": "常州市本级", "question": "汽车置换补贴怎么申请"},
        "response_mode": "blocking",
        "user": "golden-eval",
    }


def test_extract_answer_supports_chat_and_workflow_shapes() -> None:
    mod = _load_module()

    assert mod.extract_dify_answer({"answer": "chat answer"}) == "chat answer"
    assert mod.extract_dify_answer({"data": {"outputs": {"answer": "workflow answer"}}}) == "workflow answer"
    assert mod.extract_dify_answer({"data": {"outputs": {"result": "workflow result"}}}) == "workflow result"


def test_extract_response_refs_supports_chat_and_workflow_shapes() -> None:
    mod = _load_module()

    assert mod.extract_dify_response_refs(
        {
            "conversation_id": "conv-chat",
            "message_id": "msg-chat",
            "task_id": "task-chat",
            "workflow_run_id": "run-chat",
        }
    ) == {
        "conversation_id": "conv-chat",
        "message_id": "msg-chat",
        "task_id": "task-chat",
        "workflow_run_id": "run-chat",
    }
    assert mod.extract_dify_response_refs(
        {
            "data": {
                "conversation_id": "conv-workflow",
                "message_id": "msg-workflow",
                "task_id": "task-workflow",
                "workflow_run_id": "run-workflow",
            }
        }
    ) == {
        "conversation_id": "conv-workflow",
        "message_id": "msg-workflow",
        "task_id": "task-workflow",
        "workflow_run_id": "run-workflow",
    }


def test_diagnose_dify_error_extracts_missing_start_variable() -> None:
    mod = _load_module()

    detail = (
        'HTTP 400: {"code": "invalid_param", '
        '"message": "Run failed: Variable #1711528914102.areaName# not found", '
        '"status": 400}'
    )

    assert mod.diagnose_dify_error(detail) == {
        "http_status": 400,
        "dify_error_code": "invalid_param",
        "dify_error_message": "Run failed: Variable #1711528914102.areaName# not found",
        "error_kind": "missing_start_variable",
        "missing_variable_selector": "1711528914102.areaName",
        "missing_variable": "areaName",
    }


def test_load_api_key_file_reads_token_without_leaking_shape(tmp_path: Path) -> None:
    mod = _load_module()
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps({"token": "app-secret-token"}), encoding="utf-8")

    assert mod.load_api_key("", str(key_path), env={}) == "app-secret-token"


def test_request_json_retries_transient_url_errors(monkeypatch) -> None:
    mod = _load_module()
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"answer": "ok"}).encode("utf-8")

    def fake_urlopen(_request, timeout: float):
        nonlocal calls
        calls += 1
        assert timeout == 12.0
        if calls == 1:
            raise URLError("temporary ssl eof")
        return FakeResponse()

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)

    assert (
        mod._request_json(
            url="https://dify.test/v1/chat-messages",
            payload={"query": "q"},
            api_key="secret-token",
            timeout=12.0,
        )
        == {"answer": "ok"}
    )
    assert calls == 2


def test_request_json_retries_transient_dify_http_errors(monkeypatch) -> None:
    mod = _load_module()
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"answer": "ok"}).encode("utf-8")

    def fake_urlopen(_request, timeout: float):
        nonlocal calls
        calls += 1
        assert timeout == 12.0
        if calls == 1:
            raise mod.HTTPError(
                url="https://dify.test/v1/chat-messages",
                code=400,
                msg="bad request",
                hdrs=None,
                fp=io.BytesIO(
                    b'{"code":"invalid_param","message":"Run failed: timed out","status":400}'
                ),
            )
        return FakeResponse()

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert (
        mod._request_json(
            url="https://dify.test/v1/chat-messages",
            payload={"query": "q"},
            api_key="secret-token",
            timeout=12.0,
        )
        == {"answer": "ok"}
    )
    assert calls == 2


def test_request_json_does_not_retry_missing_variable_http_errors(monkeypatch) -> None:
    mod = _load_module()
    calls = 0

    def fake_urlopen(_request, timeout: float):
        nonlocal calls
        calls += 1
        assert timeout == 12.0
        raise mod.HTTPError(
            url="https://dify.test/v1/chat-messages",
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(
                b'{"code":"invalid_param","message":"Run failed: Variable #1711528914102.areaName# not found","status":400}'
            ),
        )

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)

    try:
        mod._request_json(
            url="https://dify.test/v1/chat-messages",
            payload={"query": "q"},
            api_key="secret-token",
            timeout=12.0,
        )
    except RuntimeError as exc:
        assert "areaName" in str(exc)
    else:
        raise AssertionError("expected missing variable error")
    assert calls == 1


def test_collect_answers_returns_answers_json_with_errors() -> None:
    mod = _load_module()
    calls: list[tuple[str, dict, str]] = []
    progress: list[dict] = []

    def fake_request(*, url: str, payload: dict, api_key: str, timeout: float) -> dict:
        calls.append((url, payload, api_key))
        if payload.get("query") == "bad":
            raise RuntimeError("boom")
        return {
            "answer": f"answer for {payload['query']}",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
        }

    report = mod.collect_answers(
        cases=[
            {"id": "ok-case", "query": "good"},
            {"id": "bad-case", "query": "bad"},
        ],
        base_url="http://dify.test/v1",
        api_key="token",
        mode="chat",
        user="tester",
        response_mode="blocking",
        workflow_query_key="query",
        timeout=12.0,
        request_json=fake_request,
        progress_fn=progress.append,
        generated_at="2026-06-07T01:02:03Z",
    )

    assert calls[0][0] == "http://dify.test/v1/chat-messages"
    assert calls[0][1]["query"] == "good"
    assert calls[0][2] == "token"
    assert report["generated_at"] == "2026-06-07T01:02:03Z"
    assert report["summary"] == {"cases": 2, "succeeded": 1, "failed": 1}
    assert report["answers"][0]["answer"] == "answer for good"
    assert report["answers"][0]["conversation_id"] == "conv-1"
    assert report["answers"][0]["message_id"] == "msg-1"
    assert report["answers"][1]["error"] == "boom"
    assert progress == [
        {"stage": "collect", "event": "case", "index": 1, "total": 2, "id": "ok-case", "ok": True},
        {"stage": "collect", "event": "case", "index": 2, "total": 2, "id": "bad-case", "ok": False},
    ]


def test_collect_answers_preserves_traceable_area_input_without_leaking_other_inputs() -> None:
    mod = _load_module()

    def fake_request(**_kwargs):  # noqa: ANN003, ANN202
        return {"answer": "ok", "message_id": "msg-1"}

    report = mod.collect_answers(
        cases=[
            {
                "id": "case-1",
                "query": "新北区社保卡补卡在哪里办理",
                "dify_inputs": {"areaName": "新北区", "operatorToken": "secret-should-not-be-reported"},
            }
        ],
        base_url="http://dify.test/v1",
        api_key="token",
        mode="chat",
        user="tester",
        response_mode="blocking",
        workflow_query_key="query",
        timeout=12.0,
        request_json=fake_request,
    )

    assert report["answers"][0]["dify_inputs"] == {"areaName": "新北区"}
    assert "operatorToken" not in json.dumps(report, ensure_ascii=False)
    assert "secret-should-not-be-reported" not in json.dumps(report, ensure_ascii=False)


def test_collect_answers_classifies_missing_start_variable_errors() -> None:
    mod = _load_module()

    def fake_request(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError(
            'HTTP 400: {"code": "invalid_param", '
            '"message": "Run failed: Variable #1711528914102.areaName# not found", '
            '"status": 400}'
        )

    report = mod.collect_answers(
        cases=[{"id": "case-1", "query": "经开区社保卡补卡在哪里办理"}],
        base_url="http://dify.test/v1",
        api_key="token",
        mode="chat",
        user="tester",
        response_mode="blocking",
        workflow_query_key="query",
        timeout=12.0,
        request_json=fake_request,
    )

    assert report["summary"] == {
        "cases": 1,
        "succeeded": 0,
        "failed": 1,
        "missing_start_variable_errors": 1,
    }
    assert report["answers"][0]["error_kind"] == "missing_start_variable"
    assert report["answers"][0]["missing_variable_selector"] == "1711528914102.areaName"
    assert report["answers"][0]["missing_variable"] == "areaName"


def test_collect_answers_report_includes_endpoint_without_api_key() -> None:
    mod = _load_module()

    def fake_request(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("request failed")

    report = mod.collect_answers(
        cases=[{"id": "case-1", "query": "问题"}],
        base_url="http://dify.test/v1/",
        api_key="secret-token-should-not-leak",
        mode="workflow",
        user="tester",
        response_mode="blocking",
        workflow_query_key="query",
        timeout=12.0,
        request_json=fake_request,
    )

    text = json.dumps(report, ensure_ascii=False)
    assert report["source"]["endpoint_url"] == "http://dify.test/v1/workflows/run"
    assert "secret-token-should-not-leak" not in text
