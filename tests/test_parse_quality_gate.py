from __future__ import annotations


def test_evaluate_parse_quality_gate_flags_small_model_pipeline_risks() -> None:
    from app.parsing.processors.parse_quality_gate import evaluate_parse_quality_gate

    decision = evaluate_parse_quality_gate(
        {
            "parse_quality": {"score": 0.52},
            "ocr": {"confidence_avg": 0.61, "low_confidence_spans": [{"page": 1, "text": "模糊"}]},
            "watermark_removal": {"removed_count": 18, "input_count": 40},
            "reading_order_fix": {"changed": True, "items": 20, "column_pages": 3},
            "table_store": {
                "tables": [
                    {"row_count": 6200, "col_count": 14, "table_id": "large-table"},
                ],
            },
        }
    )

    payload = decision.to_metadata()
    assert payload["schema"] == "mimirq.parse_quality_gate.v1"
    assert payload["grade"] == "fail"
    assert payload["needs_review"] is True
    assert payload["flags"]["parse_score_low"] is True
    assert payload["flags"]["ocr_low_confidence"] is True
    assert payload["flags"]["noise_removal_risky"] is True
    assert payload["flags"]["reading_order_unstable"] is True
    assert payload["flags"]["tag_sidecar_recommended"] is True
    assert payload["actions"]["tag_sidecar_recommended"] is True
    assert "large-table" in payload["evidence"]["large_tables"][0]["table_id"]


def test_apply_parse_quality_gate_metadata_keeps_parse_quality_flags_near_score() -> None:
    from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata

    meta = apply_parse_quality_gate_metadata(
        {
            "parse_quality": {"score": 0.91},
            "ocr_confidence_avg": 0.88,
            "watermark_removal": {"removed_count": 1, "input_count": 100},
            "reading_order_fix": {"changed": False, "items": 120, "column_pages": 0},
            "table_store": {"tables": [{"row_count": 10, "col_count": 4, "table_id": "ok"}]},
        }
    )

    assert meta["parse_quality_gate"]["grade"] == "pass"
    assert meta["parse_quality_gate"]["needs_review"] is False
    assert meta["parse_quality"]["needs_review"] is False
    assert meta["parse_quality"]["gate_grade"] == "pass"
    assert meta["parse_quality"]["flags"]["ocr_low_confidence"] is False
    assert meta["parse_quality_flags"]["tag_sidecar_recommended"] is False
