from scripts import schedule_parse_repair as repair


def test_collect_from_object_merges_all_supported_risk_sources() -> None:
    bucket: dict[str, repair.Candidate] = {}
    payload = [
        {
            "parse_risk_summary": {
                "top_low_quality_documents": [
                    {"document_id": "doc-a", "score": 0.3},
                    "invalid",
                ],
                "parse_risk_tail": [
                    {"document_id": "doc-a", "score": 0.1},
                    {"document_id": "doc-b", "score": 0.8},
                ],
            },
            "parse_risk_tail_drift": {
                "added_document_ids": ["doc-b", "doc-c", ""],
            },
            "candidates": [
                {"document_id": "doc-a", "risk_score": 0.5, "reason": "manual"},
                {"document_id": "doc-d", "score": 0.4},
                "invalid",
            ],
        },
        {"candidates": [{"document_id": "doc-a", "risk_score": 3.0, "reason": "urgent"}]},
        "ignored",
    ]

    repair._collect_from_object(payload, source_name="risk.json", bucket=bucket)

    assert set(bucket) == {"doc-a", "doc-b", "doc-c", "doc-d"}
    assert bucket["doc-a"].risk_score == 1.0
    assert bucket["doc-a"].reasons == {
        "parse_risk_summary_low_quality",
        "parse_risk_tail",
        "manual",
        "urgent",
    }
    assert bucket["doc-a"].sources == {"risk.json"}
    assert bucket["doc-b"].risk_score == 1.0
    assert bucket["doc-b"].reasons == {"parse_risk_tail", "parse_risk_tail_added"}
    assert bucket["doc-c"].risk_score == 1.0
    assert bucket["doc-d"].risk_score == 0.6
    assert bucket["doc-d"].reasons == {"candidate"}
