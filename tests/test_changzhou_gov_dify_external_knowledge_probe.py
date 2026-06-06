from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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


def test_collect_probe_report_flags_dify_empty_but_mimirq_direct_ok_without_leaking_key() -> None:
    mod = _load_module()

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
    )

    text = json.dumps(report, ensure_ascii=False)
    assert "external-secret-key" not in text
    assert report["summary"]["cases"] == 1
    assert report["summary"]["dify_hit_empty"] == 1
    assert report["summary"]["mimirq_direct_nonempty"] == 1
    assert report["summary"]["mimirq_direct_schema_valid"] == 1
    assert report["summary"]["dify_runtime_empty_but_mimirq_direct_ok"] == 1
    assert report["source"]["endpoint_host"] == "192.0.2.6"
    assert report["source"]["endpoint_host_is_local"] is True
    assert report["source"]["local_ipv4_addresses"] == ["192.0.2.6"]
    assert report["cases"][0]["diagnosis"] == "dify_runtime_empty_but_mimirq_direct_ok"
    assert report["cases"][0]["dify_dataset_id"] == "ds-xinbei"
    assert report["cases"][0]["mimirq_direct_schema_valid"] is True
    assert report["cases"][0]["mimirq_direct_schema_errors"] == []
    assert report["cases"][0]["mimirq_direct_first_title"] == "01政务服务事项知识/新北区事项清单.txt"


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
