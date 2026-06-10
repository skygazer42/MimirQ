from __future__ import annotations

import importlib.util
import json
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


def test_changzhou_golden_eval_reuses_pipeline_contract_metadata_view_keys() -> None:
    text = Path("scripts/changzhou_gov_golden_eval.py").read_text(encoding="utf-8")

    assert "from app.rag.pipeline_plugins.contracts import" in text
    assert "DISPLAY_METADATA_KEY" in text
    assert "EVALUABLE_METADATA_KEY" in text
    assert '_PUBLIC_METADATA_VIEW_KEYS = ("_evaluable_metadata", "_display_metadata")' not in text


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


def test_evaluate_case_reports_expected_metadata_quality() -> None:
    mod = _load_module()
    case = {
        "id": "south-permit",
        "query": "south district permit renewal",
        "expected": {"metadata": {"region": "south"}},
    }
    records = [
        {"title": "north.md", "content": "permit renewal", "metadata": {"region": "north"}},
        {"title": "south.md", "content": "permit renewal", "metadata": {"region": "south"}},
    ]

    result = mod.evaluate_case(case, records)

    assert result["metadata_quality"] == {
        "evaluated": True,
        "expected": {"region": "south"},
        "first_match_rank": 2,
        "top_1_match": False,
        "top_3_match": True,
        "top_5_match": True,
    }


def test_evaluate_case_matches_expected_metadata_from_evaluable_view() -> None:
    mod = _load_module()
    case = {
        "id": "south-permit-nested-metadata",
        "query": "south district permit renewal",
        "expected": {"metadata": {"region": "south"}},
    }
    records = [
        {
            "title": "south.md",
            "content": "permit renewal",
            "metadata": {"_evaluable_metadata": {"region": "south"}},
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["hit_rank"] == 1
    assert result["hit_at_1"] is True
    assert result["metadata_quality"]["first_match_rank"] == 1
    assert result["metadata_quality"]["top_1_match"] is True


def test_evaluate_case_accepts_derived_source_record_id_variants() -> None:
    mod = _load_module()
    case = {
        "id": "duplicate-service-item",
        "query": "经开区分公司注销登记在哪里办理",
        "expected": {
            "metadata": {
                "knowledge_section": "01政务服务事项知识",
                "source_record_id": "14786d21876b77f20264dc4a",
                "gov_knowledge_type": "service_item",
                "district": "经开区",
                "service_name": "分公司注销登记（设区的市级权限）",
            },
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/经开区事项清单.txt",
            "content": "事项名称：分公司注销登记（设区的市级权限）\n办理地点：A8",
            "metadata": {
                "knowledge_section": "01政务服务事项知识",
                "source_record_id": "14786d21876b77f20264dc4a-2981db422ab4",
                "gov_knowledge_type": "service_item",
                "district": "经开区",
                "service_name": "分公司注销登记（设区的市级权限）",
            },
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["hit_rank"] == 1
    assert result["metadata_quality"]["first_match_rank"] == 1


def test_evaluate_case_rejects_derived_source_record_id_when_other_metadata_differs() -> None:
    mod = _load_module()
    case = {
        "id": "duplicate-service-item-wrong-service",
        "query": "经开区分公司注销登记在哪里办理",
        "expected": {
            "metadata": {
                "knowledge_section": "01政务服务事项知识",
                "source_record_id": "14786d21876b77f20264dc4a",
                "gov_knowledge_type": "service_item",
                "district": "经开区",
                "service_name": "分公司注销登记（设区的市级权限）",
            },
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/经开区事项清单.txt",
            "content": "事项名称：分公司设立登记（设区的市级权限）\n办理地点：A8",
            "metadata": {
                "knowledge_section": "01政务服务事项知识",
                "source_record_id": "14786d21876b77f20264dc4a-2981db422ab4",
                "gov_knowledge_type": "service_item",
                "district": "经开区",
                "service_name": "分公司设立登记（设区的市级权限）",
            },
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["hit_rank"] is None
    assert result["metadata_quality"]["first_match_rank"] is None


def test_evaluate_case_reports_kg_hint_diagnostics() -> None:
    mod = _load_module()
    case = {
        "id": "kg-scope",
        "query": "alpha recovery path",
        "expected": {
            "content_contains": ["alpha recovery"],
            "chunk_ids": ["chunk-a"],
        },
    }
    records = [
        {
            "title": "alpha.md",
            "content": "alpha recovery",
            "chunk_id": "chunk-a",
            "retrieval_role": "kgq",
            "kg_pagerank": 0.6,
            "kg_shared_events": 2,
            "kg_path_length": 2,
            "kg_evidence_anchored": True,
        },
        {
            "title": "noise.md",
            "content": "unrelated",
            "metadata": {
                "chunk_id": "chunk-b",
                "retrieval_role": "kg",
                "kg_pagerank": 0.2,
                "kg_shared_events": 1,
            },
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["kg_hint_diagnostics"]["kg_candidate_count"] == 2
    assert result["kg_hint_diagnostics"]["kg_query_expansion_record_count"] == 1
    assert result["kg_hint_diagnostics"]["kg_entity_anchor_record_count"] == 1
    assert result["kg_hint_diagnostics"]["kg_relation_neighbor_record_count"] == 2
    assert result["kg_hint_diagnostics"]["kg_noise_evaluated"] is True
    assert result["kg_hint_diagnostics"]["kg_noise_record_count"] == 1


def test_evaluate_case_uses_expected_metadata_for_kg_noise_scope() -> None:
    mod = _load_module()
    case = {
        "id": "metadata-kg-scope",
        "query": "south district permit renewal",
        "expected": {
            "metadata": {"region": "south", "ticket_type": "permit"},
        },
    }
    records = [
        {
            "title": "south.md",
            "content": "permit renewal",
            "metadata": {
                "retrieval_role": "kgq",
                "kg_pagerank": 0.6,
                "_evaluable_metadata": {"region": "south", "ticket_type": "permit"},
            },
        },
        {
            "title": "north.md",
            "content": "permit renewal",
            "metadata": {
                "retrieval_role": "kg",
                "kg_pagerank": 0.2,
                "_evaluable_metadata": {"region": "north", "ticket_type": "permit"},
            },
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["kg_hint_diagnostics"]["kg_noise_evaluated"] is True
    assert result["kg_hint_diagnostics"]["kg_noise_record_count"] == 1
    assert result["kg_hint_diagnostics"]["kg_noise_rate"] == 0.5


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


def test_summarize_results_reports_expected_metadata_match_rates() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {
                "hit_rank": 1,
                "metadata_quality": {
                    "evaluated": True,
                    "top_1_match": True,
                    "top_3_match": True,
                    "top_5_match": True,
                },
            },
            {
                "hit_rank": 2,
                "metadata_quality": {
                    "evaluated": True,
                    "top_1_match": False,
                    "top_3_match": True,
                    "top_5_match": True,
                },
            },
            {"hit_rank": 1, "metadata_quality": {"evaluated": False}},
        ]
    )

    assert summary["expected_metadata_cases"] == 2
    assert summary["expected_metadata_case_rate"] == 2 / 3
    assert summary["top_1_expected_metadata_match_rate"] == 0.5
    assert summary["top_3_expected_metadata_match_rate"] == 1.0
    assert summary["top_5_expected_metadata_match_rate"] == 1.0
    assert summary["top_1_expected_metadata_mismatch_cases"] == 1
    assert summary["top_3_expected_metadata_mismatch_cases"] == 0
    assert summary["top_5_expected_metadata_mismatch_cases"] == 0


def test_summarize_results_reports_required_section_coverage() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {
                "hit_rank": 1,
                "case_scope": {
                    "expected_metadata": {"knowledge_section": "alpha"},
                    "knowledge_section": "alpha",
                    "has_expected_metadata": True,
                    "has_knowledge_section": True,
                },
            },
            {
                "hit_rank": 1,
                "case_scope": {
                    "expected_metadata": {"knowledge_section": "beta"},
                    "knowledge_section": "beta",
                    "has_expected_metadata": True,
                    "has_knowledge_section": True,
                },
            },
            {
                "hit_rank": 1,
                "case_scope": {
                    "expected_metadata": {"chunk_kind": "qa_pair"},
                    "knowledge_section": "",
                    "has_expected_metadata": True,
                    "has_knowledge_section": False,
                },
            },
        ],
        required_sections=("alpha", "beta", "gamma"),
    )

    assert summary["knowledge_section_cases"] == {"alpha": 1, "beta": 1}
    assert summary["required_sections"] == ["alpha", "beta", "gamma"]
    assert summary["covered_required_sections"] == ["alpha", "beta"]
    assert summary["missing_required_sections"] == ["gamma"]
    assert summary["required_section_coverage_rate"] == 2 / 3
    assert summary["section_expected_metadata_case_rate"] == 2 / 3
    assert summary["missing_knowledge_section_cases"] == 1


def test_summarize_results_reports_kg_hint_diagnostics() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {
                "hit_rank": 1,
                "kg_hint_diagnostics": {
                    "kg_candidate_count": 2,
                    "kg_query_expansion_record_count": 1,
                    "kg_entity_anchor_record_count": 1,
                    "kg_relation_neighbor_record_count": 2,
                    "kg_boosted_record_count": 2,
                    "kg_noise_evaluated": True,
                    "kg_noise_record_count": 1,
                },
            },
            {
                "hit_rank": 1,
                "kg_hint_diagnostics": {
                    "kg_candidate_count": 1,
                    "kg_query_expansion_record_count": 0,
                    "kg_entity_anchor_record_count": 0,
                    "kg_relation_neighbor_record_count": 1,
                    "kg_boosted_record_count": 1,
                    "kg_noise_evaluated": False,
                    "kg_noise_record_count": 0,
                },
            },
        ]
    )

    assert summary["kg_hint_cases"] == 2
    assert summary["kg_candidate_cases"] == 2
    assert summary["kg_candidate_case_rate"] == 1.0
    assert summary["kg_candidate_records"] == 3
    assert summary["kg_query_expansion_records"] == 1
    assert summary["kg_entity_anchor_records"] == 1
    assert summary["kg_relation_neighbor_records"] == 3
    assert summary["kg_boosted_records"] == 3
    assert summary["kg_noise_evaluated_cases"] == 1
    assert summary["kg_noise_records"] == 1
    assert summary["kg_noise_rate"] == 0.5


def test_changzhou_golden_cases_cover_expected_metadata_scope() -> None:
    payload = json.loads(Path("plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json").read_text())
    cases = payload.get("cases") if isinstance(payload, dict) else []
    metadata_schema = json.loads(
        Path("plugins/pipelines/changzhou-gov-service-knowledge/metadata_schema.json").read_text()
    )
    declared_fields = {
        field["name"]
        for field in metadata_schema.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }
    with_expected_metadata = [
        case
        for case in cases
        if isinstance(case.get("expected"), dict)
        and isinstance(case["expected"].get("metadata"), dict)
        and case["expected"]["metadata"]
    ]
    referenced_fields = {
        field_name
        for case in with_expected_metadata
        for field_name in case["expected"]["metadata"]
    }

    assert len(cases) == 13
    assert len(with_expected_metadata) / len(cases) >= 0.8
    assert referenced_fields <= declared_fields
    assert all(case["expected"]["metadata"].get("knowledge_section") for case in with_expected_metadata)


def test_changzhou_retrieval_profile_gates_required_section_coverage() -> None:
    mod = _load_module()
    args = mod.build_arg_parser().parse_args(["--quality-profile", "changzhou-retrieval"])

    thresholds = mod._thresholds_from_args(args)

    assert thresholds["required_section_coverage_rate"] == 1.0
    assert thresholds["section_expected_metadata_case_rate"] == 1.0
    assert mod.quality_profile_required_sections("changzhou-retrieval") == (
        "01政务服务事项知识",
        "02高效办成一件事",
        "03常州市常见问题",
        "04专题常见问答",
        "05业务部门常见问题",
        "06各区常见问题",
    )


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
        "effective_records": 2,
        "evaluated_records": 2,
        "effective_context_rate": 1.0,
        "noise_rate": 0.0,
    }


def test_evaluate_case_reports_retrieval_noise_from_top_context() -> None:
    mod = _load_module()
    case = {
        "id": "social-card-location",
        "query": "社保卡在哪里补办",
        "answer_context_top_k": 3,
        "expected": {
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
            "title": "noise.txt",
            "content": "这是一个关于公积金贷款额度的片段。",
            "metadata": {},
        },
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": "办理地点：新北区政务服务中心",
            "metadata": {},
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["answer_quality"]["effective_records"] == 2
    assert result["answer_quality"]["evaluated_records"] == 3
    assert result["answer_quality"]["effective_context_rate"] == 2 / 3
    assert result["answer_quality"]["noise_rate"] == 1 - (2 / 3)


def test_evaluate_case_accepts_long_cjk_key_point_word_order_variation() -> None:
    mod = _load_module()
    case = {
        "id": "xinbei-precursor-chemicals",
        "query": "新北区第三类非药品类易制毒化学品经营备案在哪里办理",
        "expected": {
            "answer_key_points": ["第三类非药品类易制毒化学品经营备案"],
        },
    }
    records = [
        {
            "title": "01政务服务事项知识/新北区事项清单.txt",
            "content": (
                "事项名称：经营第三类非药品类易制毒化学品备案\n"
                "办理地点：常州市新北区新桥街道云河路69号“两馆两中心”档案馆4楼429办公室危化处"
            ),
            "metadata": {},
        },
    ]

    result = mod.evaluate_case(case, records)

    assert result["answer_quality"]["grounded"] is True
    assert result["answer_quality"]["missing_key_points"] == []


def test_summarize_results_reports_answer_quality() -> None:
    mod = _load_module()

    summary = mod.summarize_results(
        [
            {
                "hit_rank": 1,
                "answer_quality": {
                    "key_points_total": 2,
                    "key_points_matched": 2,
                    "grounded": True,
                    "effective_records": 2,
                    "evaluated_records": 3,
                },
            },
            {
                "hit_rank": 1,
                "answer_quality": {
                    "key_points_total": 2,
                    "key_points_matched": 1,
                    "grounded": False,
                    "effective_records": 1,
                    "evaluated_records": 2,
                },
            },
            {"hit_rank": 1, "answer_quality": {"key_points_total": 0, "key_points_matched": 0, "grounded": True}},
        ]
    )

    assert summary["answer_cases"] == 2
    assert summary["answer_grounding_rate"] == 0.5
    assert summary["answer_key_point_recall"] == 0.75
    assert summary["answer_missing_cases"] == 1
    assert summary["retrieval_effective_context_rate"] == 3 / 5
    assert summary["retrieval_noise_rate"] == 1 - (3 / 5)
    assert summary["retrieval_effective_records"] == 3
    assert summary["retrieval_evaluated_records"] == 5


def test_quality_gate_accepts_retrieval_effective_and_noise_thresholds() -> None:
    mod = _load_module()

    passed = mod.evaluate_quality_gate(
        {"retrieval_effective_context_rate": 0.8, "retrieval_noise_rate": 0.2},
        {"retrieval_effective_context_rate": 0.75},
        {"retrieval_noise_rate": 0.25},
    )
    failed = mod.evaluate_quality_gate(
        {"retrieval_effective_context_rate": 0.6, "retrieval_noise_rate": 0.4},
        {"retrieval_effective_context_rate": 0.75},
        {"retrieval_noise_rate": 0.25},
    )

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert [check["metric"] for check in failed["checks"]] == [
        "retrieval_effective_context_rate",
        "retrieval_noise_rate",
    ]


def test_changzhou_retrieval_profile_blocks_known_scope_regression() -> None:
    mod = _load_module()
    args = mod.build_arg_parser().parse_args(["--quality-profile", "changzhou-retrieval"])
    summary = {
        "hit_at_1": 0.72,
        "hit_at_3": 0.75,
        "hit_at_5": 0.75,
        "answer_grounding_rate": 0.77,
        "answer_key_point_recall": 0.77,
        "retrieval_effective_context_rate": 0.6038647342995169,
        "retrieval_noise_rate": 0.3961352657004831,
        "kg_noise_rate": 0.2,
    }

    gate = mod.evaluate_quality_gate(summary, mod._thresholds_from_args(args), mod._maximums_from_args(args))

    assert gate["passed"] is False
    failed_metrics = {check["metric"] for check in gate["checks"] if check["passed"] is False}
    assert failed_metrics == {
        "hit_at_1",
        "hit_at_3",
        "hit_at_5",
        "answer_grounding_rate",
        "answer_key_point_recall",
        "retrieval_effective_context_rate",
        "expected_metadata_case_rate",
        "section_expected_metadata_case_rate",
        "required_section_coverage_rate",
        "top_1_expected_metadata_match_rate",
        "top_3_expected_metadata_match_rate",
        "top_5_expected_metadata_match_rate",
        "retrieval_noise_rate",
        "kg_noise_rate",
    }


def test_changzhou_retrieval_profile_gates_expected_metadata_scope() -> None:
    mod = _load_module()
    args = mod.build_arg_parser().parse_args(["--quality-profile", "changzhou-retrieval"])

    thresholds = mod._thresholds_from_args(args)

    assert thresholds["expected_metadata_case_rate"] == 1.0
    assert thresholds["top_1_expected_metadata_match_rate"] == 0.95
    assert thresholds["top_3_expected_metadata_match_rate"] == 0.98
    assert thresholds["top_5_expected_metadata_match_rate"] == 0.98


def test_changzhou_retrieval_profile_gates_kg_noise_when_available() -> None:
    mod = _load_module()
    args = mod.build_arg_parser().parse_args(["--quality-profile", "changzhou-retrieval"])

    maximums = mod._maximums_from_args(args)
    gate = mod.evaluate_quality_gate({"kg_noise_rate": 0.2}, {}, maximums)

    assert maximums["kg_noise_rate"] == 0.1
    assert gate["passed"] is False
    assert any(
        check == {"metric": "kg_noise_rate", "actual": 0.2, "maximum": 0.1, "passed": False}
        for check in gate["checks"]
    )


def test_changzhou_retrieval_profile_allows_explicit_threshold_overrides() -> None:
    mod = _load_module()
    args = mod.build_arg_parser().parse_args(
        [
            "--quality-profile",
            "changzhou-retrieval",
            "--min-hit-at-1",
            "1",
            "--min-expected-metadata-case-rate",
            "0.8",
            "--min-top-1-expected-metadata-match-rate",
            "0.95",
            "--min-top-3-expected-metadata-match-rate",
            "1",
            "--max-retrieval-noise-rate",
            "0.05",
            "--max-kg-noise-rate",
            "0.03",
        ]
    )

    assert mod._thresholds_from_args(args)["hit_at_1"] == 1.0
    assert mod._thresholds_from_args(args)["expected_metadata_case_rate"] == 0.8
    assert mod._thresholds_from_args(args)["top_1_expected_metadata_match_rate"] == 0.95
    assert mod._thresholds_from_args(args)["top_3_expected_metadata_match_rate"] == 1.0
    assert mod._maximums_from_args(args)["retrieval_noise_rate"] == 0.05
    assert mod._maximums_from_args(args)["kg_noise_rate"] == 0.03


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
        "policy_clean": True,
        "forbidden_phrases": [],
        "missing_key_points": ["0519-88516920"],
    }


def test_evaluate_case_flags_generated_answer_instruction_leakage() -> None:
    mod = _load_module()
    case = {
        "id": "one-thing-social-card-operation",
        "query": "社会保障卡居民服务一件事网上办理怎么操作",
        "expected": {
            "answer_key_points": ["选择“个人登录”"],
        },
    }
    records = [
        {
            "title": "02高效办成一件事/一件事操作指引.txt",
            "content": "1.点击社会保障卡居民服务“一件事”模块。选择“个人登录”。",
            "metadata": {},
        }
    ]
    answer_item = {
        "answer": (
            "必须按顺序包含以下标题：\n"
            "1. 点击社会保障卡居民服务“一件事”模块，选择“个人登录”。"
        )
    }

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"]["policy_clean"] is False
    assert result["generated_answer_quality"]["grounded"] is False
    assert result["generated_answer_quality"]["forbidden_phrases"] == ["必须按顺序包含以下标题"]


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
        "policy_clean": True,
        "forbidden_phrases": [],
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
        "policy_clean": True,
        "forbidden_phrases": [],
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
        "policy_clean": True,
        "forbidden_phrases": [],
        "missing_key_points": [],
    }


def test_city_car_replacement_generated_answer_matches_2025_application_alias() -> None:
    mod = _load_module()
    payload = json.loads(Path("plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json").read_text())
    cases = payload.get("cases") if isinstance(payload, dict) else []
    case = next(item for item in cases if item.get("id") == "city-car-replacement-subsidy")
    records = [
        {
            "title": "03常州市常见问题/常州市高频应用知识.xlsx",
            "content": (
                "2025年汽车置换更新补贴申请时间为2025年1月1日至12月31日。"
                "申请入口为苏服办APP，补贴分为卖旧置换和报废置换两种类型。"
            ),
            "metadata": {},
        }
    ]
    answer_item = {
        "answer": (
            "2025年汽车置换更新补贴申请时间为2025年1月1日至12月31日，"
            "申请入口为“苏服办”APP。补贴分为卖旧置换和报废置换两种类型。"
        )
    }

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"]["grounded"] is True
    assert result["generated_answer_quality"]["missing_key_points"] == []


def test_city_car_replacement_generated_answer_matches_2025_policy_date_alias() -> None:
    mod = _load_module()
    payload = json.loads(Path("plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json").read_text())
    cases = payload.get("cases") if isinstance(payload, dict) else []
    case = next(item for item in cases if item.get("id") == "city-car-replacement-subsidy")
    records = [
        {
            "title": "03常州市常见问题/常州市高频应用知识.xlsx",
            "content": (
                "汽车置换更新可以在苏服办APP申请，可以申请卖旧置换更新补贴和报废置换更新补贴。"
                "转让车辆须在2025年1月8日前登记在本人名下。"
            ),
            "metadata": {},
        }
    ]
    answer_item = {
        "answer": (
            "您可通过苏服办APP搜索汽车置换更新应用进行申请，补贴分为卖旧置换和报废置换两种类型。"
            "旧车需在2025年1月8日前登记。"
        )
    }

    result = mod.evaluate_case(case, records, generated_answer=answer_item)

    assert result["generated_answer_quality"]["grounded"] is True
    assert result["generated_answer_quality"]["missing_key_points"] == []


def test_run_live_eval_report_includes_generated_at(monkeypatch) -> None:
    mod = _load_module()
    payloads: list[dict[str, object]] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        payloads.append(kwargs["payload"])
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

    assert payloads[0]["retrieval_setting"] == {"top_k": 5, "score_threshold": 0.0}
    assert report["generated_at"] == "2026-06-07T01:02:03Z"
    assert report["source"] == {"base_url": "http://mimirq.test", "base_host": "mimirq.test"}
    assert report["summary"]["cases"] == 1
    assert report["results"][0]["hit_rank"] == 1


def test_run_live_eval_can_force_kg_mode_in_retrieval_payload(monkeypatch) -> None:
    mod = _load_module()
    payloads: list[dict[str, object]] = []

    def fake_request_json(**kwargs):  # noqa: ANN003, ANN202
        payloads.append(kwargs["payload"])
        return {"records": []}

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    mod.run_live_eval(
        cases=[
            {
                "id": "case-1",
                "knowledge_id": "changzhou_新北区_service",
                "query": "新北区社保卡补卡在哪里办理",
                "expected": {},
            }
        ],
        base_url="http://mimirq.test",
        token="secret-token",
        top_k=5,
        timeout=12.0,
        kg_mode="on",
    )

    assert payloads[0]["retrieval_setting"] == {
        "top_k": 5,
        "score_threshold": 0.0,
        "enable_kg_query_expansion": True,
        "enable_kg_chunk_injection": True,
        "enable_kg_chunk_boost": True,
    }


def test_build_arg_parser_accepts_kg_mode() -> None:
    mod = _load_module()

    args = mod.build_arg_parser().parse_args(["--kg-mode", "off"])

    assert args.kg_mode == "off"


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


def test_load_report_requires_summary_object(tmp_path: Path) -> None:
    mod = _load_module()
    report_path = tmp_path / "report.json"
    report_path.write_text('{"results": []}', encoding="utf-8")

    try:
        mod.load_report(str(report_path))
    except ValueError as exc:
        assert "summary" in str(exc)
    else:
        raise AssertionError("load_report should reject reports without summary")


def test_main_report_mode_rechecks_quality_gate_without_token(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    mod = _load_module()
    report_path = tmp_path / "regressed-report.json"
    out_path = tmp_path / "gated-report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "hit_at_1": 0.72,
                    "hit_at_3": 0.75,
                    "hit_at_5": 0.75,
                    "answer_grounding_rate": 0.77,
                    "answer_key_point_recall": 0.77,
                    "retrieval_effective_context_rate": 0.6038647342995169,
                    "retrieval_noise_rate": 0.3961352657004831,
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", raising=False)

    rc = mod.main(
        [
            "--report",
            str(report_path),
            "--quality-profile",
            "changzhou-retrieval",
            "--out",
            str(out_path),
        ]
    )

    assert rc == mod.QUALITY_GATE_EXIT_CODE
    gated = json.loads(out_path.read_text(encoding="utf-8"))
    assert gated["gate"]["passed"] is False
    assert any(check["metric"] == "retrieval_noise_rate" and not check["passed"] for check in gated["gate"]["checks"])


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


def _passing_changzhou_summary(**overrides: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "cases": 13,
        "hit_at_1": 1.0,
        "hit_at_3": 1.0,
        "hit_at_5": 1.0,
        "mrr": 1.0,
        "answer_grounding_rate": 1.0,
        "answer_key_point_recall": 1.0,
        "retrieval_effective_context_rate": 1.0,
        "expected_metadata_case_rate": 1.0,
        "section_expected_metadata_case_rate": 1.0,
        "required_section_coverage_rate": 1.0,
        "top_1_expected_metadata_match_rate": 1.0,
        "top_3_expected_metadata_match_rate": 1.0,
        "top_5_expected_metadata_match_rate": 1.0,
        "retrieval_noise_rate": 0.0,
        "kg_noise_rate": 0.0,
    }
    summary.update(overrides)
    return summary


def test_compare_reports_passes_when_candidate_preserves_quality_with_bounded_kg_noise() -> None:
    mod = _load_module()
    baseline = {"summary": _passing_changzhou_summary(kg_candidate_records=0)}
    candidate = {"summary": _passing_changzhou_summary(kg_candidate_records=8, kg_noise_rate=0.05)}

    report = mod.compare_reports(
        baseline,
        candidate,
        thresholds=mod.quality_profile_thresholds("changzhou-retrieval"),
        maximums=mod.quality_profile_maximums("changzhou-retrieval"),
    )

    assert report["schema"] == "mimirq.changzhou_gov_service_knowledge.golden_compare.v1"
    assert report["summary"]["passed"] is True
    assert report["summary"]["failed"] == 0
    assert any(check["metric"] == "hit_at_1" and check["passed"] is True for check in report["checks"])
    assert report["candidate_gate"]["passed"] is True


def test_compare_reports_fails_candidate_quality_gate_and_metric_drop() -> None:
    mod = _load_module()
    baseline = {"summary": _passing_changzhou_summary(hit_at_1=1.0)}
    candidate = {
        "summary": _passing_changzhou_summary(
            hit_at_1=0.9,
            kg_noise_rate=0.2,
        )
    }

    report = mod.compare_reports(
        baseline,
        candidate,
        thresholds=mod.quality_profile_thresholds("changzhou-retrieval"),
        maximums=mod.quality_profile_maximums("changzhou-retrieval"),
    )

    assert report["summary"]["passed"] is False
    failed_metrics = {check["metric"] for check in report["checks"] if check["passed"] is False}
    gate_failed_metrics = {
        check["metric"] for check in report["candidate_gate"]["checks"] if check["passed"] is False
    }
    assert "hit_at_1" in failed_metrics
    assert "hit_at_1" in gate_failed_metrics
    assert "kg_noise_rate" in gate_failed_metrics


def test_main_compare_report_mode_writes_gate_without_token(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    mod = _load_module()
    baseline_path = tmp_path / "kg-off.json"
    candidate_path = tmp_path / "kg-on.json"
    out_path = tmp_path / "compare.json"
    baseline_path.write_text(json.dumps({"summary": _passing_changzhou_summary()}), encoding="utf-8")
    candidate_path.write_text(
        json.dumps({"summary": _passing_changzhou_summary(kg_candidate_records=5, kg_noise_rate=0.05)}),
        encoding="utf-8",
    )
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", raising=False)

    rc = mod.main(
        [
            "--baseline-report",
            str(baseline_path),
            "--candidate-report",
            str(candidate_path),
            "--quality-profile",
            "changzhou-retrieval",
            "--out",
            str(out_path),
        ]
    )

    assert rc == 0
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["summary"]["passed"] is True
    assert saved["candidate_gate"]["passed"] is True
