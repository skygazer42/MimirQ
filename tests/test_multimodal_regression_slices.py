from types import SimpleNamespace

from app.rag.evaluation.multimodal_slices import (
    MULTIMODAL_GOLDEN_SLICE_SCHEMA_V1,
    classify_regression_case_multimodal_slice,
    summarize_multimodal_regression_slices,
)
from app.rag.evaluation.regression_sample_builder import build_regression_item_meta


def test_classifies_golden_cases_for_multimodal_slices() -> None:
    chart_case = SimpleNamespace(
        question="图表中 2025 年收入同比增长多少？",
        tags=["chart"],
        extra={},
    )
    formula_case = SimpleNamespace(
        question="根据公式 ROE = 净利润 / 权益 计算结果",
        tags=[],
        extra={"modality": "formula"},
    )
    table_math_case = SimpleNamespace(
        question="表格里 Top 3 客户占比是多少？",
        tags=["table-math"],
        extra={},
    )

    assert classify_regression_case_multimodal_slice(chart_case) == "chart"
    assert classify_regression_case_multimodal_slice(formula_case) == "formula"
    assert classify_regression_case_multimodal_slice(table_math_case) == "table_math"


def test_summarizes_multimodal_regression_slices_for_run_summary() -> None:
    summary = summarize_multimodal_regression_slices(
        [
            {
                "item_meta": {"golden_multimodal_slice": "chart"},
                "retrieved_contexts": ["chart context"],
                "citations": [{"chunk_id": "c1"}],
                "abstain_triggered": False,
            },
            {
                "item_meta": {"golden_multimodal_slice": "formula"},
                "retrieved_contexts": [],
                "citations": [],
                "abstain_triggered": True,
            },
            {
                "item_meta": {"slice_modality": "image"},
                "retrieved_contexts": ["image context"],
                "citations": [],
                "abstain_triggered": False,
            },
        ]
    )

    assert summary["schema"] == MULTIMODAL_GOLDEN_SLICE_SCHEMA_V1
    assert summary["items"] == 3
    assert summary["counts"]["chart"] == 1
    assert summary["counts"]["formula"] == 1
    assert summary["counts"]["image"] == 1
    assert summary["evaluatable"]["chart"] == 1
    assert summary["evaluatable"]["formula"] == 0
    assert summary["abstained"]["formula"] == 1
    assert summary["coverage"]["chart"] == 1.0
    assert summary["coverage"]["formula"] == 0.0


def test_regression_item_meta_persists_golden_multimodal_slice() -> None:
    meta = build_regression_item_meta(
        sample_kwargs={"reference_context_ids": ["ref"], "retrieved_context_ids": ["ret"]},
        item_meta={"golden_multimodal_slice": "chart", "slice_modality": "image"},
    )

    assert meta["golden_multimodal_slice"] == "chart"
    assert meta["slice_modality"] == "image"
