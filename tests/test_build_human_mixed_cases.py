import importlib.util
from pathlib import Path


def _load_builder():  # noqa: ANN202
    path = (
        Path(__file__).parents[1] / "plugins/pipelines/changzhou-gov-service-knowledge/tools/build_human_mixed_cases.py"
    )
    spec = importlib.util.spec_from_file_location("build_human_mixed_cases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_thing_question_uses_declared_evidence_dimensions() -> None:
    builder = _load_builder()
    case = {
        "id": "case-b",
        "case_type": "one_thing_guide_composite",
        "source_record_title": "Example Package",
        "subquestions": [
            {"id": "申请材料"},
            {"id": "办理渠道"},
            {"id": "联系方式"},
            {"id": "办理流程"},
        ],
    }

    question = builder._human_question(case)

    assert "申请材料、办理渠道、联系方式、办理流程" in question
    assert "涉及事项" not in question


def test_fallback_question_preserves_ordered_evidence_dimensions() -> None:
    builder = _load_builder()
    case = {
        "id": "case-a",
        "case_type": "service_item_composite",
        "source_record_title": "Example Service",
        "subquestions": [{"id": "字段甲"}, {"id": "字段乙"}, {"id": "字段丙"}],
    }

    question = builder._human_question(case)

    assert "字段甲、字段乙、字段丙" in question


def _service_case(case_id: str, **fields: str) -> dict:
    return {
        "id": case_id,
        "case_type": "service_item_composite",
        "source_record_title": f"Service {case_id}",
        "source_record_fields": {
            "事项名称": f"Service {case_id}",
            **fields,
        },
    }


def test_build_prioritizes_non_qa_cases_and_respects_qa_cap() -> None:
    builder = _load_builder()
    service = _service_case("service", 办理材料="身份证", 办理地点="政务中心", 收费情况="免费")
    fallback = {
        "id": "fallback",
        "case_type": "one_thing_guide_composite",
        "source_record_title": "Fallback package",
        "subquestions": [{"id": "申请材料"}],
    }
    qa_case = {
        "id": "qa",
        "case_type": "qa_faq",
        "source_record_title": "FAQ entry",
        "source_section": "03常州市常见问题",
    }

    selected = builder.build_human_mixed_cases(
        [service, dict(service), qa_case, fallback],
        total=4,
        max_qa_ratio=0.25,
    )

    assert [item["id"] for item in selected] == ["service", "fallback", "qa"]
    assert [item["qa_like_source"] for item in selected] == [False, False, True]
    assert selected[0]["dimension_signature"] == "办理材料+办理地点+收费情况"
    assert selected[1]["case_generation"] == builder.CASE_GENERATION


def test_build_rotates_distinct_dimension_profiles_before_qa() -> None:
    builder = _load_builder()
    service = _service_case(
        "service",
        办理材料="身份证",
        办理地点="政务中心",
        收费情况="免费",
        受理条件="年满十八周岁",
        承诺办结时限="三个工作日",
        咨询方式="12345",
    )

    selected = builder.build_human_mixed_cases([service], total=2, max_qa_ratio=0.0)

    assert len(selected) == 2
    assert selected[0]["id"] == "service"
    assert selected[1]["case_variant_of"] == "service"
    assert selected[1]["case_variant_reason"] == "additional_distinct_dimension_profile"
    assert selected[0]["dimension_signature"] != selected[1]["dimension_signature"]


def test_build_returns_empty_for_non_positive_total() -> None:
    builder = _load_builder()

    assert builder.build_human_mixed_cases([{"id": "unused"}], total=0) == []
