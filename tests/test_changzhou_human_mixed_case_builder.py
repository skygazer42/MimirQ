from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/build_changzhou_human_mixed_cases.py")
    spec = importlib.util.spec_from_file_location("build_changzhou_human_mixed_cases", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _service_case(case_id: str, title: str, *, source_section: str = "01政务服务事项知识") -> dict:
    return {
        "id": case_id,
        "question": f"我要办理“{title}”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
        "query": f"我要办理“{title}”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
        "case_type": "service_item_composite",
        "source_section": source_section,
        "source_record_title": title,
        "subquestions": [
            {"id": "办理材料", "required_clause_ids": ["materials"]},
            {"id": "办理地点", "required_clause_ids": ["location"]},
            {"id": "收费情况", "required_clause_ids": ["fee"]},
        ],
        "evidence_clauses": [
            {"id": "materials", "required_terms": [f"事项名称：{title}", "办理材料：", "身份证"]},
            {"id": "location", "required_terms": [f"事项名称：{title}", "办理地点：", "政务服务中心"]},
            {"id": "fee", "required_terms": [f"事项名称：{title}", "收费情况：", "不收费"]},
        ],
    }


def _rich_service_case(case_id: str, title: str) -> dict:
    case = _service_case(case_id, title)
    case["source_record_fields"] = {
        "事项名称": title,
        "办理材料": "身份证（必要）",
        "办理地点": "政务服务中心综合窗口",
        "收费情况": "不收费",
        "受理条件": "申请材料齐全、符合法定形式",
        "承诺办结时限": "3个工作日",
        "咨询方式": "0519-12345",
        "办理形式": "窗口办理,网上办理",
        "在线办理地址": "https://example.test/apply",
        "办理流程": "受理、审核、办结",
        "办理时间": "工作日上午9点至下午5点",
        "监督投诉方式": "0519-12345",
    }
    return case


def test_human_mixed_case_builder_caps_qa_like_sources_and_marks_fill_variants() -> None:
    mod = _load_module()
    cases = [
        _rich_service_case("svc-1", "社会保障卡补卡"),
        _rich_service_case("svc-2", "学历公证"),
        _rich_service_case("svc-3", "森林、林木所有权登记"),
        _service_case("svc-from-faq", "核发居民身份证（换领）", source_section="03常州市常见问题"),
        {
            "id": "qa-1",
            "question": "关于居住证，请合并回答：在哪里办理、需要多长时间、是否收费或需要注意什么？",
            "query": "关于居住证，请合并回答：在哪里办理、需要多长时间、是否收费或需要注意什么？",
            "case_type": "qa_multi_fact_composite",
            "source_section": "03常州市常见问题",
            "source_record_title": "居住证",
            "subquestions": [{"id": "问题1", "required_clause_ids": ["qa-1"]}],
            "evidence_clauses": [{"id": "qa-1", "required_terms": ["居住证", "不收费"]}],
        },
    ]

    selected = mod.build_human_mixed_cases(cases, total=6, max_qa_ratio=0.17)

    assert len(selected) == 6
    assert sum(1 for case in selected if mod.is_qa_like_case(case)) <= 1
    assert any(case.get("case_variant_of") for case in selected)
    assert all("请合并回答" not in case["question"] for case in selected)
    assert all("同时告诉我" not in case["question"] for case in selected)
    assert all(case["query"] == case["question"] for case in selected)
    assert all("human_mixed_v1" == case.get("case_generation") for case in selected)


def test_human_mixed_case_builder_fill_cases_use_distinct_dimension_signatures() -> None:
    mod = _load_module()
    selected = mod.build_human_mixed_cases([_rich_service_case("svc-1", "社会保障卡补卡")], total=4, max_qa_ratio=0.0)

    signatures = [case["dimension_signature"] for case in selected]

    assert len(selected) == 4
    assert len(set(signatures)) == 4
    assert signatures[0] == "办理材料+办理地点+收费情况"
    assert "受理条件+承诺办结时限+咨询方式" in signatures
    assert "办理形式+在线办理地址+办理流程" in signatures
    assert all(case.get("case_variant_reason") != "filled_target_total_after_qa_cap" for case in selected[1:])
    assert all("地址" not in case.get("case_variant_reason", "") for case in selected[1:])


def test_human_mixed_case_builder_prioritizes_globally_distinct_dimensions() -> None:
    mod = _load_module()
    cases = [_rich_service_case(f"svc-{index}", f"事项{index}") for index in range(1, 9)]

    selected = mod.build_human_mixed_cases(cases, total=8, max_qa_ratio=0.0)
    signatures = [case["dimension_signature"] for case in selected]

    assert len(selected) == 8
    assert len(set(signatures)) == 8


def test_human_mixed_case_builder_uses_natural_templates_by_case_type() -> None:
    mod = _load_module()
    guide = {
        "id": "guide-1",
        "question": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "query": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "case_type": "one_thing_guide_composite",
        "source_section": "02高效办成一件事",
        "source_record_title": "教育入学“一件事”",
        "subquestions": [
            {"id": "涉及事项", "required_clause_ids": ["guide-1"]},
            {"id": "申请材料", "required_clause_ids": ["guide-2"]},
            {"id": "办理渠道", "required_clause_ids": ["guide-3"]},
        ],
        "evidence_clauses": [
            {"id": "guide-1", "required_terms": ["教育入学“一件事”", "涉及事项"]},
            {"id": "guide-2", "required_terms": ["教育入学“一件事”", "申请材料"]},
            {"id": "guide-3", "required_terms": ["教育入学“一件事”", "办理渠道"]},
        ],
    }

    selected = mod.build_human_mixed_cases([_service_case("svc-1", "社会保障卡补卡"), guide], total=2)
    questions = {case["id"]: case["question"] for case in selected}

    assert "准备办" in questions["svc-1"] or "办" in questions["svc-1"]
    assert "带什么" in questions["svc-1"] or "材料" in questions["svc-1"]
    assert "一件事" in questions["guide-1"]
    assert "从哪里办" in questions["guide-1"] or "入口" in questions["guide-1"]


def test_human_mixed_case_builder_includes_non_qa_complex_files_before_service_variants() -> None:
    mod = _load_module()
    guide_1 = {
        "id": "guide-1",
        "question": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "query": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "case_type": "one_thing_guide_composite",
        "source_section": "02高效办成一件事",
        "source_record_title": "教育入学“一件事”",
        "subquestions": [
            {"id": "涉及事项", "required_clause_ids": ["guide-1"]},
            {"id": "申请材料", "required_clause_ids": ["guide-2"]},
            {"id": "办理渠道", "required_clause_ids": ["guide-3"]},
        ],
        "evidence_clauses": [
            {"id": "guide-1", "required_terms": ["教育入学“一件事”", "涉及事项"]},
            {"id": "guide-2", "required_terms": ["教育入学“一件事”", "申请材料"]},
            {"id": "guide-3", "required_terms": ["教育入学“一件事”", "办理渠道"]},
        ],
    }
    guide_2 = {**guide_1, "id": "guide-2", "source_record_title": "开办餐饮店“一件事”"}
    cases = [
        _rich_service_case("svc-1", "社会保障卡补卡"),
        _rich_service_case("svc-2", "学历公证"),
        guide_1,
        guide_2,
    ]

    selected = mod.build_human_mixed_cases(cases, total=4, max_qa_ratio=0.0)

    assert [case["id"] for case in selected] == ["svc-1", "svc-2", "guide-1", "guide-2"]
    assert sum(1 for case in selected if case.get("case_variant_of")) == 0
    assert {case["source_section"] for case in selected} == {"01政务服务事项知识", "02高效办成一件事"}


def test_human_mixed_case_builder_counts_complex_file_subjects_as_distinct_dimensions() -> None:
    mod = _load_module()
    guide_1 = {
        "id": "guide-1",
        "question": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "query": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "case_type": "one_thing_guide_composite",
        "source_section": "02高效办成一件事",
        "source_record_title": "教育入学“一件事”",
        "subquestions": [
            {"id": "涉及事项", "required_clause_ids": ["guide-1"]},
            {"id": "申请材料", "required_clause_ids": ["guide-2"]},
            {"id": "办理渠道", "required_clause_ids": ["guide-3"]},
        ],
        "evidence_clauses": [
            {"id": "guide-1", "required_terms": ["教育入学“一件事”", "涉及事项"]},
            {"id": "guide-2", "required_terms": ["教育入学“一件事”", "申请材料"]},
            {"id": "guide-3", "required_terms": ["教育入学“一件事”", "办理渠道"]},
        ],
    }
    guide_2 = {**guide_1, "id": "guide-2", "source_record_title": "开办餐饮店“一件事”"}

    selected = mod.build_human_mixed_cases([guide_1, guide_2], total=2, max_qa_ratio=0.0)
    signatures = [case["dimension_signature"] for case in selected]

    assert len(set(signatures)) == 2
    assert signatures == [
        "教育入学“一件事”::涉及事项+申请材料+办理渠道",
        "开办餐饮店“一件事”::涉及事项+申请材料+办理渠道",
    ]


def test_human_mixed_case_builder_rebuilds_one_thing_evidence_from_section_labels() -> None:
    mod = _load_module()
    guide = {
        "id": "guide-1",
        "question": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "query": "我想办理“教育入学“一件事””，请同时说明涉及哪些事项、主要材料，以及线上/线下办理渠道或联系电话。",
        "case_type": "one_thing_guide_composite",
        "source_section": "02高效办成一件事",
        "source_record_title": "教育入学“一件事”",
        "subquestions": [
            {"id": "涉及事项", "required_clause_ids": ["old-1"]},
            {"id": "申请材料", "required_clause_ids": ["old-2"]},
            {"id": "办理渠道", "required_clause_ids": ["old-3"]},
        ],
        "evidence_clauses": [
            {"id": "old-1", "required_terms": ["教育入学“一件事”", "随机办理须知长句"]},
            {"id": "old-2", "required_terms": ["教育入学“一件事”", "地区 咨询电话 溧阳市"]},
            {"id": "old-3", "required_terms": ["教育入学“一件事”", "旧入口片段"]},
        ],
    }

    selected = mod.build_human_mixed_cases([guide], total=1, max_qa_ratio=0.0)
    case = selected[0]

    assert case["subquestions"] == [
        {"id": "涉及事项", "required_clause_ids": ["涉及事项-1"]},
        {"id": "申请材料", "required_clause_ids": ["申请材料-2"]},
        {"id": "办理渠道", "required_clause_ids": ["办理渠道-3"]},
    ]
    assert case["evidence_clauses"] == [
        {
            "id": "涉及事项-1",
            "required_terms": ["一件事：教育入学“一件事”", "涉及事项："],
            "match_scope": "record",
        },
        {
            "id": "申请材料-2",
            "required_terms": ["一件事：教育入学“一件事”", "申请材料："],
            "match_scope": "record",
        },
        {
            "id": "办理渠道-3",
            "required_terms": ["一件事：教育入学“一件事”", "办理入口："],
            "match_scope": "record",
        },
    ]
