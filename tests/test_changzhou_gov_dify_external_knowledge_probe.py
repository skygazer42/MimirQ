from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import URLError


def _load_module():
    path = Path("scripts/changzhou_gov_dify_external_knowledge_probe.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_external_knowledge_probe", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_knowledge_dataset_map_reads_external_dataset_details() -> None:
    mod = _load_module()
    requested: list[str] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        path = kwargs["path"]
        requested.append(path)
        if path == "/datasets/ds-xinbei":
            return {
                "id": "ds-xinbei",
                "name": "MimirQ-新北区政务服务知识检索",
                "provider": "external",
                "external_knowledge_info": {"external_knowledge_id": "changzhou_新北区_service"},
                "external_retrieval_model": {"top_k": 2, "score_threshold": 0.0},
            }
        if path == "/datasets/ds-city":
            return {
                "id": "ds-city",
                "name": "MimirQ-常州市政务服务知识检索",
                "provider": "external",
                "external_knowledge_info": {"external_knowledge_id": "changzhou_city_service"},
            }
        raise AssertionError(path)

    mapping = mod.build_knowledge_dataset_map(
        dataset_bindings=[
            {"id": "ds-xinbei", "name": "MimirQ-新北区政务服务知识检索"},
            {"id": "ds-city", "name": "MimirQ-常州市政务服务知识检索"},
        ],
        console_base_url="https://dify.test/console/api",
        console_token="console-secret",
        request_json=fake_request_json,
        timeout=12.0,
    )

    assert requested == ["/datasets/ds-xinbei", "/datasets/ds-city"]
    assert mapping["changzhou_新北区_service"]["dataset_id"] == "ds-xinbei"
    assert mapping["changzhou_city_service"]["dataset_name"] == "MimirQ-常州市政务服务知识检索"
    assert mapping["changzhou_新北区_service"]["external_retrieval_model"] == {
        "top_k": 2,
        "score_threshold": 0.0,
    }


def test_request_json_retries_transient_url_errors(monkeypatch) -> None:
    mod = _load_module()
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"data": []}).encode("utf-8")

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
            console_base_url="https://dify.test/console/api",
            console_token="secret-console-token",
            path="/datasets/external-knowledge-api?page=1&limit=50",
            timeout=12.0,
        )
        == {"data": []}
    )
    assert calls == 2


def test_request_json_retries_transient_read_timeout(monkeypatch) -> None:
    mod = _load_module()
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"data": []}).encode("utf-8")

    def fake_urlopen(_request, timeout: float):
        nonlocal calls
        calls += 1
        assert timeout == 12.0
        if calls == 1:
            raise TimeoutError("The read operation timed out")
        return FakeResponse()

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)

    assert (
        mod._request_json(
            console_base_url="https://dify.test/console/api",
            console_token="secret-console-token",
            path="/datasets/external-knowledge-api?page=1&limit=50",
            timeout=12.0,
        )
        == {"data": []}
    )
    assert calls == 2


def test_format_cli_error_adds_login_hint_for_expired_console_token() -> None:
    mod = _load_module()

    message = mod._format_cli_error(RuntimeError('HTTP 401: {"code":"unauthorized","message":"Token has expired."}'))

    assert "Token has expired" in message
    assert "make dify-console-login" in message
    assert "DIFY_CONSOLE_PASSWORD_FILE" in message
    assert "secret" not in message.lower()


def test_collect_probe_report_flags_dify_empty_but_mimirq_direct_ok_without_leaking_key() -> None:
    mod = _load_module()
    progress: list[dict] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        path = kwargs["path"]
        if path == "/datasets/external-knowledge-api?page=1&limit=50":
            return {
                "data": [
                    {
                        "id": "api-1",
                        "name": "MimirQ-192.0.2.6",
                        "settings": {
                            "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
                            "api_key": "external-secret-key",
                        },
                        "dataset_bindings": [{"id": "ds-xinbei", "name": "MimirQ-新北区政务服务知识检索"}],
                    }
                ]
            }
        if path == "/datasets/ds-xinbei":
            return {
                "id": "ds-xinbei",
                "name": "MimirQ-新北区政务服务知识检索",
                "provider": "external",
                "external_knowledge_info": {"external_knowledge_id": "changzhou_新北区_service"},
            }
        if path == "/datasets/ds-xinbei/external-hit-testing":
            assert kwargs["method"] == "POST"
            assert kwargs["payload"]["query"] == "新北区社保卡补卡在哪里办理"
            assert kwargs["payload"]["external_retrieval_model"] == {
                "top_k": 5,
                "score_threshold": 0,
                "score_threshold_enabled": False,
            }
            return {"query": {"content": kwargs["payload"]["query"]}, "records": []}
        raise AssertionError(path)

    def fake_mimirq_direct(**kwargs):  # noqa: ANN003, ANN202
        assert kwargs["endpoint"] == "http://192.0.2.6:8000/api/v1/integrations/dify"
        assert kwargs["api_key"] == "external-secret-key"
        assert kwargs["knowledge_id"] == "changzhou_新北区_service"
        return {
            "records": [
                {
                    "score": 0.73,
                    "title": "01政务服务事项知识/新北区事项清单.txt",
                    "content": "事项名称：社会保障卡补卡",
                }
            ]
        }

    report = mod.collect_probe_report(
        cases=[
            {
                "id": "case-1",
                "knowledge_id": "changzhou_新北区_service",
                "query": "新北区社保卡补卡在哪里办理",
            }
        ],
        external_api_id="api-1",
        console_base_url="https://dify.test/console/api",
        console_token="console-secret",
        request_json=fake_request_json,
        request_mimirq_direct=fake_mimirq_direct,
        local_ipv4_addresses=["192.0.2.6"],
        timeout=12.0,
        top_k=5,
        progress_fn=progress.append,
        generated_at="2026-06-07T01:02:03Z",
    )

    text = json.dumps(report, ensure_ascii=False)
    assert "external-secret-key" not in text
    assert report["generated_at"] == "2026-06-07T01:02:03Z"
    assert report["summary"]["cases"] == 1
    assert report["summary"]["dify_hit_empty"] == 1
    assert report["summary"]["mimirq_direct_nonempty"] == 1
    assert report["summary"]["mimirq_direct_schema_valid"] == 1
    assert report["summary"]["dify_runtime_empty_but_mimirq_direct_ok"] == 1
    assert report["gate"]["passed"] is False
    assert "dify_hit_nonempty" in report["gate"]["failed_conditions"]
    assert report["source"]["endpoint_host"] == "192.0.2.6"
    assert report["source"]["endpoint_host_is_local"] is True
    assert report["source"]["endpoint_host_matches_local_machine"] is True
    assert report["source"]["endpoint_host_is_loopback"] is False
    assert report["source"]["local_ipv4_addresses"] == ["192.0.2.6"]
    assert report["boundary"] == {
        "endpoint_config_ok": True,
        "local_mimirq_direct_ok": True,
        "dify_hit_testing_ok": False,
        "verdict": "dify_runtime_empty_but_mimirq_direct_ok",
    }
    assert report["cases"][0]["diagnosis"] == "dify_runtime_empty_but_mimirq_direct_ok"
    assert report["cases"][0]["dify_dataset_id"] == "ds-xinbei"
    assert report["cases"][0]["mimirq_direct_schema_valid"] is True
    assert report["cases"][0]["mimirq_direct_schema_errors"] == []
    assert report["cases"][0]["mimirq_direct_first_title"] == "01政务服务事项知识/新北区事项清单.txt"
    assert progress == [
        {
            "stage": "external_probe",
            "event": "case",
            "index": 1,
            "total": 1,
            "id": "case-1",
            "dify_hit_records": 0,
            "mimirq_direct_records": 1,
            "diagnosis": "dify_runtime_empty_but_mimirq_direct_ok",
        }
    ]


def test_collect_probe_report_retries_transient_case_read_timeout() -> None:
    mod = _load_module()
    hit_attempts = 0
    direct_attempts = 0

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        nonlocal hit_attempts
        path = kwargs["path"]
        if path == "/datasets/external-knowledge-api?page=1&limit=50":
            return {
                "data": [
                    {
                        "id": "api-1",
                        "name": "MimirQ-192.0.2.6",
                        "settings": {
                            "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
                            "api_key": "external-secret-key",
                        },
                        "dataset_bindings": [{"id": "ds-city", "name": "MimirQ-常州市政务服务知识检索"}],
                    }
                ]
            }
        if path == "/datasets/ds-city":
            return {
                "id": "ds-city",
                "name": "MimirQ-常州市政务服务知识检索",
                "provider": "external",
                "external_knowledge_info": {"external_knowledge_id": "changzhou_city_service"},
            }
        if path == "/datasets/ds-city/external-hit-testing":
            hit_attempts += 1
            if hit_attempts == 1:
                raise TimeoutError("The read operation timed out")
            return {"records": [{"title": "常州市本级12345QA.txt", "score": 0.9, "content": "查询进度"}]}
        raise AssertionError(path)

    def fake_mimirq_direct(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal direct_attempts
        direct_attempts += 1
        return {"records": [{"title": "常州市本级12345QA.txt", "score": 0.9, "content": "查询进度"}]}

    report = mod.collect_probe_report(
        cases=[
            {
                "id": "case-1",
                "knowledge_id": "changzhou_city_service",
                "query": "如何查询身份证办理进度？",
            }
        ],
        external_api_id="api-1",
        console_base_url="https://dify.test/console/api",
        console_token="console-secret",
        request_json=fake_request_json,
        request_mimirq_direct=fake_mimirq_direct,
        local_ipv4_addresses=["192.0.2.6"],
        timeout=12.0,
        top_k=5,
    )

    assert hit_attempts == 2
    assert direct_attempts == 1
    assert report["summary"]["probe_errors"] == 0
    assert report["summary"]["dify_hit_nonempty"] == 1
    assert report["summary"]["mimirq_direct_nonempty"] == 1
    assert report["gate"]["passed"] is True
    assert report["cases"][0]["diagnosis"] == "dify_hit_testing_ok"


def test_evaluate_probe_gate_rejects_loopback_endpoint_and_incomplete_coverage() -> None:
    mod = _load_module()

    passing = mod.evaluate_probe_gate(
        {
            "source": {"endpoint": "https://mimirq.example.com/api/v1/integrations/dify", "endpoint_host_is_loopback": False},
            "summary": {
                "cases": 2,
                "dify_hit_nonempty": 2,
                "mimirq_direct_nonempty": 2,
                "mimirq_direct_schema_valid": 2,
                "probe_errors": 0,
            },
        }
    )
    assert passing == {"passed": True, "failed_conditions": []}

    failing = mod.evaluate_probe_gate(
        {
            "source": {"endpoint": "http://127.0.0.1:8000/api/v1/integrations/dify", "endpoint_host_is_loopback": True},
            "summary": {
                "cases": 2,
                "dify_hit_nonempty": 1,
                "mimirq_direct_nonempty": 2,
                "mimirq_direct_schema_valid": 1,
                "probe_errors": 1,
            },
        }
    )
    assert failing == {
        "passed": False,
        "failed_conditions": [
            "endpoint_host_is_loopback",
            "dify_hit_nonempty",
            "mimirq_direct_schema_valid",
            "probe_errors",
        ],
    }


def test_evaluate_probe_gate_allows_nonlocal_routable_endpoint_when_hits_pass() -> None:
    mod = _load_module()

    gate = mod.evaluate_probe_gate(
        {
            "source": {
                "endpoint": "https://mimirq.internal/api/v1/integrations/dify",
                "endpoint_host_is_loopback": False,
                "endpoint_host_matches_local_machine": False,
            },
            "summary": {
                "cases": 1,
                "dify_hit_nonempty": 1,
                "mimirq_direct_nonempty": 1,
                "mimirq_direct_schema_valid": 1,
                "probe_errors": 0,
            },
        }
    )

    assert gate == {"passed": True, "failed_conditions": []}


def test_probe_boundary_verdict_passes_when_dify_and_direct_hits_pass() -> None:
    mod = _load_module()

    boundary = mod.build_boundary_verdict(
        {
            "source": {
                "endpoint": "http://192.0.2.6:8000/api/v1/integrations/dify",
                "endpoint_host_is_loopback": False,
            },
            "summary": {
                "cases": 2,
                "dify_hit_nonempty": 2,
                "mimirq_direct_nonempty": 2,
                "mimirq_direct_schema_valid": 2,
                "dify_runtime_empty_but_mimirq_direct_ok": 0,
                "probe_errors": 0,
            },
        }
    )

    assert boundary == {
        "endpoint_config_ok": True,
        "local_mimirq_direct_ok": True,
        "dify_hit_testing_ok": True,
        "verdict": "dify_external_boundary_ok",
    }


def test_validate_dify_external_records_shape_rejects_null_metadata_and_bad_score() -> None:
    mod = _load_module()

    assert mod.validate_dify_external_records_shape(
        {"records": [{"content": "c", "score": 0.8, "title": "t", "metadata": {}}]}
    ) == []

    assert mod.validate_dify_external_records_shape(
        {
            "records": [
                {"content": "", "score": 0.8, "title": "t", "metadata": {}},
                {"content": "c", "score": 2, "title": "t", "metadata": None},
            ]
        }
    ) == [
        "records[0].content must be a non-empty string",
        "records[1].score must be between 0 and 1",
        "records[1].metadata must be an object when present",
    ]
