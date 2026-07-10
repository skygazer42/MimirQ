from __future__ import annotations

from pathlib import Path

import pytest

from scripts import changzhou_gov_eval_pack as mod


def test_parse_service_item_file_extracts_title_and_fields(tmp_path: Path) -> None:
    path = tmp_path / "新北区事项清单.txt"
    path.write_text(
        "\n".join(
            [
                "[事项名称：社会保障卡补卡]",
                "办理地点：新北区政务服务中心三楼18、19号窗口",
                "咨询方式：0519-88516920",
                "收费情况：不收费",
                "==##########==",
            ]
        ),
        encoding="utf-8",
    )

    records = mod.parse_service_item_file(path)

    assert len(records) == 1
    assert records[0].title == "社会保障卡补卡"
    assert records[0].district == "新北区"
    assert records[0].knowledge_id == "changzhou_新北区_service"
    assert records[0].fields["办理地点"] == "新北区政务服务中心三楼18、19号窗口"


def test_build_case_payload_respects_requested_bucket_counts() -> None:
    qa_record_a = mod.SourceRecord(
        record_id="qa-1",
        source_kind="qa_text",
        source_file="/tmp/qa-a.txt",
        source_section="06各区常见问题",
        knowledge_id="changzhou_新北区_service",
        title="社保卡补卡",
        district="新北区",
        question="新北区社保卡补卡在哪里办理？",
        answer="办理地点：新北区政务服务中心；咨询方式：0519-88516920；收费情况：不收费",
        similar_questions=["补办社保卡去哪里办", "社保卡丢了去哪补"],
        fields={},
    )
    qa_record_b = mod.SourceRecord(
        record_id="qa-2",
        source_kind="qa_text",
        source_file="/tmp/qa-b.txt",
        source_section="03常州市常见问题",
        knowledge_id="changzhou_city_service",
        title="公积金线上业务",
        district="常州市",
        question="公积金线上业务渠道有哪些？",
        answer="线上渠道包括苏服办APP和相关公积金线上业务入口。",
        similar_questions=["公积金能在手机上办吗", "线上办公积金去哪里"],
        fields={},
    )
    service_record_a = mod.SourceRecord(
        record_id="svc-1",
        source_kind="service_item",
        source_file="/tmp/service-a.txt",
        source_section="01政务服务事项知识",
        knowledge_id="changzhou_新北区_service",
        title="社会保障卡补卡",
        district="新北区",
        question="请问“社会保障卡补卡”这个事项怎么办理？",
        answer="办理地点：新北区政务服务中心；咨询方式：0519-88516920；收费情况：不收费",
        similar_questions=[],
        fields={
            "办理地点": "新北区政务服务中心",
            "咨询方式": "0519-88516920",
            "收费情况": "不收费",
            "办理材料": "身份证",
            "承诺办结时限": "1个工作日",
            "受理条件": "符合补卡条件",
            "办理形式": "窗口办理,网上办理",
            "在线办理地址": "http://example.test",
            "办理流程": "受理 审查 发证",
        },
    )
    service_record_b = mod.SourceRecord(
        record_id="svc-2",
        source_kind="service_item",
        source_file="/tmp/service-b.txt",
        source_section="01政务服务事项知识",
        knowledge_id="changzhou_新北区_service",
        title="教师资格认定",
        district="新北区",
        question="请问“教师资格认定”这个事项怎么办理？",
        answer="办理地点：市政务服务中心；咨询方式：0519-12345；收费情况：不收费",
        similar_questions=[],
        fields={
            "办理地点": "市政务服务中心",
            "咨询方式": "0519-12345",
            "收费情况": "不收费",
            "办理材料": "教师资格认定申请表",
            "承诺办结时限": "5个工作日",
            "受理条件": "符合教师资格认定条件",
            "办理形式": "网上办理",
            "在线办理地址": "http://example.edu",
            "办理流程": "申请 审核 认定",
        },
    )

    payload = mod.build_case_payload(
        records={
            "service_records": [service_record_a, service_record_b] * 4,
            "qa_records": [qa_record_a, qa_record_b] * 4,
            "one_thing_records": [],
        },
        qa_count=2,
        service_count=3,
        user_count=4,
        target_total=0,
        seed=7,
    )

    case_types = [case["case_type"] for case in payload["cases"]]
    assert case_types.count("qa_exact") == 2
    assert case_types.count("service_direct") == 3
    assert case_types.count("user_simulated") == 4


def test_build_case_payload_can_trim_user_bucket_to_target_total() -> None:
    qa_records = [
        mod.SourceRecord(
            record_id=f"qa-{idx}",
            source_kind="qa_text",
            source_file=f"/tmp/qa-{idx}.txt",
            source_section="06各区常见问题",
            knowledge_id="changzhou_新北区_service",
            title=f"社保卡补卡{idx}",
            district="新北区",
            question=f"新北区社保卡补卡问题{idx}在哪里办理？",
            answer=f"办理地点：新北区政务服务中心{idx}；咨询方式：0519-8851692{idx}；收费情况：不收费",
            similar_questions=[f"补办社保卡问题{idx}去哪里办", f"社保卡问题{idx}丢了去哪补"],
            fields={},
        )
        for idx in range(1, 4)
    ]
    service_records = [
        mod.SourceRecord(
            record_id=f"svc-{idx}",
            source_kind="service_item",
            source_file=f"/tmp/service-{idx}.txt",
            source_section="01政务服务事项知识",
            knowledge_id="changzhou_新北区_service",
            title=f"社会保障卡补卡{idx}",
            district="新北区",
            question=f"请问“社会保障卡补卡{idx}”这个事项怎么办理？",
            answer=f"办理地点：新北区政务服务中心{idx}；咨询方式：0519-8851692{idx}；收费情况：不收费",
            similar_questions=[],
            fields={
                "办理地点": f"新北区政务服务中心{idx}",
                "咨询方式": f"0519-8851692{idx}",
                "收费情况": "不收费",
                "办理材料": f"身份证{idx}",
                "承诺办结时限": "1个工作日",
                "受理条件": f"符合补卡条件{idx}",
                "办理形式": "窗口办理,网上办理",
                "在线办理地址": f"http://example.test/{idx}",
                "办理流程": "受理 审查 发证",
            },
        )
        for idx in range(1, 5)
    ]

    payload = mod.build_case_payload(
        records={
            "service_records": service_records,
            "qa_records": qa_records,
            "one_thing_records": [],
        },
        qa_count=2,
        service_count=3,
        user_count=10,
        target_total=10,
        seed=7,
    )

    summary = payload["generation_policy"]["effective"]
    case_types = [case["case_type"] for case in payload["cases"]]
    assert len(payload["cases"]) == 10
    assert summary["qa_count"] == 2
    assert summary["service_count"] == 3
    assert summary["user_count"] == 5
    assert case_types.count("user_simulated") == 5


def test_import_regression_bundle_batches_and_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, path: str, json: dict, headers: dict) -> FakeResponse:
            self.calls.append((path, json, headers))
            offset = len(self.calls)
            return FakeResponse(
                {
                    "created": 1,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [],
                    "created_case_ids": [f"case-{offset}"],
                    "updated_case_ids": [],
                    "skipped_case_ids": [],
                }
            )

    fake_client = FakeClient()
    monkeypatch.setattr(mod.httpx, "Client", lambda *a, **k: fake_client)

    bundle = {
        "dataset_id": "c1538d09-4f11-41a6-af43-806b7b46fc7b",
        "items": [{"question": f"q-{i}", "reference_sources": [{"document_id": "d", "chunk_id": "c"}]} for i in range(5)],
    }
    result = mod.import_regression_bundle(
        bundle,
        base_url="http://127.0.0.1:8000/api/v1",
        tenant_id="00000000-0000-0000-0000-000000000000",
        user_id="demo",
        overwrite=True,
        max_items=5,
        batch_size=2,
    )

    assert len(fake_client.calls) == 3
    assert result["created"] == 3
    assert result["created_case_ids"] == ["case-1", "case-2", "case-3"]


def test_create_retrieval_only_sharded_runs_forwards_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[float] = []

    def _fake_create(**kwargs):
        captured.append(float(kwargs["timeout"]))
        return {"id": f"run-{len(captured)}", "status": "pending"}

    monkeypatch.setattr(mod, "create_retrieval_only_run", _fake_create)

    out = mod.create_retrieval_only_sharded_runs(
        dataset_id="c1538d09-4f11-41a6-af43-806b7b46fc7b",
        case_ids=[str(i) for i in range(0, 520)],
        base_url="http://127.0.0.1:8000/api/v1",
        tenant_id="00000000-0000-0000-0000-000000000000",
        user_id="demo",
        shard_size=500,
        timeout=180.0,
    )

    assert captured == [180.0, 180.0]
    assert out["run_ids"] == ["run-1", "run-2"]
