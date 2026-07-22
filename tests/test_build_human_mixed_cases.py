import importlib.util
from pathlib import Path


def _load_builder():  # noqa: ANN202
    path = (
        Path(__file__).parents[1]
        / "plugins/pipelines/changzhou-gov-service-knowledge/tools/build_human_mixed_cases.py"
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
