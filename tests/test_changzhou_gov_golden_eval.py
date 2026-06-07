from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_golden_eval.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_golden_eval", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_rank_case_matches_expected_title_content_and_metadata() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-social-card-reissue",
        "query": "新北区社保卡补卡在哪里办理",
        "expected": {
            "title_contains": ["新北区事项清单"],
            "content_contains": ["事项名称：社会保障卡补卡", "办理地点：新北区"],
            "metadata": {"dataset_id": "dataset-a"},
        },
    }
    records = [
        {
            "title": "06各区常见问题/新北区12345QA.txt",
            "content": "社保补贴。",
            "metadata": {"dataset_id": "dataset-a"},
        },
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "区县：新北区\n事项名称：社会保障卡补卡\n办理地点：新北区政务服务中心",
            "metadata": {"dataset_id": "dataset-a"},
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["hit_rank"] == 2
    assert result["hit_at_1"] is False
    assert result["hit_at_3"] is True
    assert result["matched_record"]["title"] == "01政务服务事项知识/新北区事项清单.txt"


def test_summarize_results_reports_hit_rates_and_mrr() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {"hit_rank": 1},
            {"hit_rank": 3},
            {"hit_rank": None},
        ]
    )

    assert summary["cases"] == 3
    assert summary["hit_at_1"] == 1 / 3
    assert summary["hit_at_3"] == 2 / 3
    assert summary["hit_at_5"] == 2 / 3
    assert summary["mrr"] == (1 + 1 / 3) / 3
    assert summary["misses"] == 1


def test_evaluate_case_scores_answer_key_points_from_top_context() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-social-card-reissue",
        "query": "新北区社保卡补卡在哪里办理",
        "answer_context_top_k": 2,
        "expected": {
            "title_contains": ["新北区事项清单"],
            "content_contains": ["事项名称：社会保障卡补卡"],
            "answer_key_points": ["事项名称：社会保障卡补卡", "办理地点：新北区政务服务中心"],
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "事项名称：社会保障卡补卡\n办理材料：身份证件",
            "metadata": {},
        },
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "办理地点：新北区政务服务中心",
            "metadata": {},
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["answer_quality"] == {
        "key_points_total": 2,
        "key_points_matched": 2,
        "key_point_recall": 1.0,
        "grounded": True,
        "missing_key_points": [],
        "context_top_k": 2,
    }


def test_summarize_results_reports_answer_quality() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {"hit_rank": 1, "answer_quality": {"key_points_total": 2, "key_points_matched": 2, "grounded": True}},
            {"hit_rank": 1, "answer_quality": {"key_points_total": 2, "key_points_matched": 1, "grounded": False}},
            {"hit_rank": 1, "answer_quality": {"key_points_total": 0, "key_points_matched": 0, "grounded": True}},
        ]
    )

    assert summary["answer_cases"] == 2
    assert summary["answer_grounding_rate"] == 0.5
    assert summary["answer_key_point_recall"] == 0.75
    assert summary["answer_missing_cases"] == 1


def test_evaluate_case_scores_generated_answer_against_key_points() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-social-card-reissue",
        "query": "新北区社保卡补卡在哪里办理",
        "expected": {
            "answer_key_points": ["新北区政务服务中心", "0519-88516920"],
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "办理地点：新北区政务服务中心\n咨询方式：0519-88516920",
            "metadata": {},
        }
    ]
    answer_item = {"answer": "可以到新北区政务服务中心办理。"}

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"] == {
        "provided": True,
        "fallback": False,
        "key_points_total": 2,
        "key_points_matched": 1,
        "key_point_recall": 0.5,
        "grounded": False,
        "context_supported": True,
        "missing_key_points": ["0519-88516920"],
    }


def test_evaluate_case_normalizes_generated_answer_labels_without_hiding_missing_facts() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-social-card-reissue",
        "query": "新北区社保卡补卡在哪里办理",
        "expected": {
            "answer_key_points": [
                "办理地点：新北区云河路69 号新北区政务服务中心三楼18、19号窗口",
                "咨询方式：0519-88516920",
                "收费情况：不收费",
            ],
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": (
                "办理地点：新北区云河路69 号新北区政务服务中心三楼18、19号窗口\n"
                "咨询方式：0519-88516920\n收费情况：不收费"
            ),
            "metadata": {},
        }
    ]
    answer_item = {
        "answer": (
            "📍【办理地点】：新北区云河路69 号新北区政务服务中心三楼18、19号窗口\n"
            "📞【咨询方式】：0519-88516920"
        )
    }

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"] == {
        "provided": True,
        "fallback": False,
        "key_points_total": 3,
        "key_points_matched": 2,
        "key_point_recall": 2 / 3,
        "grounded": False,
        "context_supported": True,
        "missing_key_points": ["收费情况：不收费"],
    }


def test_evaluate_case_matches_structured_key_point_values_without_requiring_label() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-social-card-reissue",
        "query": "新北区社保卡补卡在哪里办理",
        "expected": {
            "answer_key_points": [
                "办理地点：新北区云河路69号",
                "咨询方式：0519-88516920",
                "收费情况：不收费",
            ],
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "办理地点：新北区云河路69号\n咨询方式：0519-88516920\n收费情况：不收费",
            "metadata": {},
        }
    ]
    answer_item = {"answer": "新北区社保卡补卡在新北区云河路69号办理，全程不收费。"}

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"] == {
        "provided": True,
        "fallback": False,
        "key_points_total": 3,
        "key_points_matched": 2,
        "key_point_recall": 2 / 3,
        "grounded": False,
        "context_supported": True,
        "missing_key_points": ["咨询方式：0519-88516920"],
    }


def test_evaluate_case_matches_key_point_aliases_for_generated_answers() -> None:
    mod = _load_module()
    case = {
        "id": "city-car-replacement-subsidy",
        "query": "汽车置换补贴怎么申请",
        "expected": {
            "answer_key_points": ["卖旧置换更新补贴", "报废置换更新补贴"],
            "answer_key_point_aliases": {
                "卖旧置换更新补贴": ["卖旧置换"],
                "报废置换更新补贴": ["报废置换"],
            },
        },
    }
    records = [
        {
            "title": "03常州市常见问题/常州市高频应用知识.xlsx",
            "content": "可以申请两种类型的补贴：卖旧置换更新补贴、报废置换更新补贴。",
            "metadata": {},
        }
    ]
    answer_item = {"answer": "补贴分为卖旧置换和报废置换两种类型。"}

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"] == {
        "provided": True,
        "fallback": False,
        "key_points_total": 2,
        "key_points_matched": 2,
        "key_point_recall": 1.0,
        "grounded": True,
        "context_supported": True,
        "missing_key_points": [],
    }


def test_run_live_eval_report_includes_generated_at(monkeypatch) -> None:
    mod = _load_module()

    def fake_request_json(**_kwargs):  # noqa: ANN003, ANN202
        return {
            "records": [
                {
                    "title": "01政务服务事项知识/新北区事项清单.txt",
                    "content": "事项名称：社会保障卡补卡",
                    "metadata": {},
                }
            ]
        }

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    report = mod.run_live_eval(
        cases=[
            {
                "id": "case-1",
                "knowledge_id": "changzhou_新北区_service",
                "query": "新北区社保卡补卡在哪里办理",
                "expected": {"content_contains": ["事项名称：社会保障卡补卡"]},
            }
        ],
        base_url="http://mimirq.test",
        token="secret-token",
        top_k=5,
        timeout=12.0,
        generated_at="2026-06-07T01:02:03Z",
    )

    assert report["generated_at"] == "2026-06-07T01:02:03Z"
    assert report["source"] == {"base_url": "http://mimirq.test", "base_host": "mimirq.test"}
    assert report["summary"]["cases"] == 1
    assert report["results"][0]["hit_rank"] == 1


def test_request_json_bypasses_proxy_for_private_mimirq_url(monkeypatch) -> None:
    mod = _load_module()
    calls: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"records":[]}'

    class FakeOpener:
        def open(self, request, *, timeout: float):
            calls["url"] = request.full_url
            calls["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(*handlers):
        calls["handlers"] = handlers
        return FakeOpener()

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("private MimirQ URLs must bypass environment proxies")

    monkeypatch.setattr(mod, "urlopen", fail_urlopen)
    monkeypatch.setattr(mod, "build_opener", fake_build_opener, raising=False)

    result = mod._request_json(
        base_url="http://192.0.2.6:8000",
        token="secret-token",
        payload={"knowledge_id": "changzhou_city_service", "query": "社保卡"},
        timeout=12.0,
    )

    assert result == {"records": []}
    assert calls["url"] == "http://192.0.2.6:8000/api/v1/integrations/dify/retrieval"
    assert calls["timeout"] == 12.0
    assert calls["handlers"]


def test_load_token_reads_env_file_without_shell_exposure(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    mod = _load_module()
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS=file-first,file-second\n", encoding="utf-8")

    assert mod.load_token("", env_file=str(env_file)) == "file-first"
    assert mod.load_token("explicit-token", env_file=str(env_file)) == "explicit-token"


def test_evaluate_case_flags_fallback_generated_answer() -> None:
    mod = _load_module()
    case = {
        "id": "fallback-case",
        "query": "社保卡在哪里补办",
        "expected": {"answer_key_points": ["政务服务中心"]},
    }
    records = [{"title": "事项", "content": "办理地点：政务服务中心", "metadata": {}}]
    answer_item = {
        "answer": "您好，“小畅”只能答复常州市政务服务领域的相关知识，例如事项或业务办理，超出领域的问题小畅暂时无法回答，您可以尝试更改描述！"
    }

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"]["provided"] is True
    assert result["generated_answer_quality"]["fallback"] is True
    assert result["generated_answer_quality"]["grounded"] is False


def test_load_answer_map_accepts_mapping_and_answers_list(tmp_path: Path) -> None:
    mod = _load_module()
    mapping_path = tmp_path / "mapping.json"
    list_path = tmp_path / "list.json"
    mapping_path.write_text(
        '{"case-a": "answer A", "case-b": {"answer": "answer B", "source": "dify"}}',
        encoding="utf-8",
    )
    list_path.write_text(
        '{"answers": [{"id": "case-c", "answer": "answer C"}, {"case_id": "case-d", "text": "answer D"}]}',
        encoding="utf-8",
    )

    mapping = mod.load_answer_map(str(mapping_path))
    listed = mod.load_answer_map(str(list_path))

    assert mapping == {
        "case-a": {"answer": "answer A"},
        "case-b": {"answer": "answer B", "source": "dify"},
    }
    assert listed == {
        "case-c": {"id": "case-c", "answer": "answer C"},
        "case-d": {"case_id": "case-d", "text": "answer D"},
    }


def test_summarize_results_reports_generated_answer_quality() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {
                "hit_rank": 1,
                "generated_answer_quality": {
                    "provided": True,
                    "key_points_total": 2,
                    "key_points_matched": 2,
                    "grounded": True,
                    "context_supported": True,
                    "fallback": False,
                },
            },
            {
                "hit_rank": 1,
                "generated_answer_quality": {
                    "provided": True,
                    "key_points_total": 2,
                    "key_points_matched": 1,
                    "grounded": False,
                    "context_supported": True,
                    "fallback": True,
                },
            },
            {"hit_rank": 1, "generated_answer_quality": {"provided": False}},
        ]
    )

    assert summary["generated_answer_cases"] == 2
    assert summary["generated_answer_grounding_rate"] == 0.5
    assert summary["generated_answer_key_point_recall"] == 0.75
    assert summary["generated_answer_context_supported_rate"] == 1.0
    assert summary["generated_answer_missing_cases"] == 1
    assert summary["generated_answer_fallback_rate"] == 0.5
    assert summary["generated_answer_fallback_cases"] == 1


def test_evaluate_quality_gate_reports_failed_thresholds() -> None:
    mod = _load_module()

    gate = mod.evaluate_quality_gate(
        {
            "hit_at_1": 0.9,
            "answer_grounding_rate": 1.0,
            "generated_answer_key_point_recall": 0.5,
        },
        {
            "hit_at_1": 1.0,
            "answer_grounding_rate": 0.9,
            "generated_answer_key_point_recall": 0.8,
        },
    )

    assert gate["passed"] is False
    assert gate["failed"] == 2
    assert gate["checks"] == [
        {"metric": "hit_at_1", "actual": 0.9, "minimum": 1.0, "passed": False},
        {"metric": "answer_grounding_rate", "actual": 1.0, "minimum": 0.9, "passed": True},
        {"metric": "generated_answer_key_point_recall", "actual": 0.5, "minimum": 0.8, "passed": False},
    ]


def test_evaluate_quality_gate_reports_failed_maximums() -> None:
    mod = _load_module()

    gate = mod.evaluate_quality_gate(
        {"generated_answer_fallback_rate": 0.5},
        {},
        {"generated_answer_fallback_rate": 0.0},
    )

    assert gate["passed"] is False
    assert gate["failed"] == 1
    assert gate["checks"] == [
        {
            "metric": "generated_answer_fallback_rate",
            "actual": 0.5,
            "maximum": 0.0,
            "passed": False,
        }
    ]


def test_report_exit_code_returns_gate_failure_code() -> None:
    mod = _load_module()

    assert mod.report_exit_code({"gate": {"passed": False}}) == 3
    assert mod.report_exit_code({"gate": {"passed": True}}) == 0
