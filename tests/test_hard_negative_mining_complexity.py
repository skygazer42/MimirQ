import json

from app.rag.evaluation.hard_negative_mining import (
    HARD_NEGATIVES_SCHEMA_V1,
    load_hard_negatives_jsonl,
    merge_hard_negative_records,
    mine_hard_negatives_for_case_from_trace,
)


def test_mine_hard_negatives_preserves_rank_dedupe_and_per_document_caps() -> None:
    case = {"reference_sources": [{"chunk_id": "positive"}]}
    trace = {
        "retrieval": {"retrieval_config_hash": "cfg-1"},
        "citations": [
            {"chunk_id": "neg-1", "document_id": "doc-a", "relevance_score": 0.9},
            {"chunk_id": "neg-1", "document_id": "doc-a", "relevance_score": 0.8},
            {"chunk_id": "neg-2", "document_id": "doc-a", "bm25_score": 0.7},
            {"chunk_id": "neg-3", "document_id": "doc-b", "vector_score": 0.6},
            {"chunk_id": "positive", "document_id": "doc-c"},
            {"chunk_id": "after", "document_id": "doc-d"},
        ],
    }

    result = mine_hard_negatives_for_case_from_trace(
        case=case,
        trace_record=trace,
        query_hash="query-1",
        max_hard_negatives=5,
        max_negatives_per_document=1,
    )

    assert result == {
        "schema": HARD_NEGATIVES_SCHEMA_V1,
        "query_hash": "query-1",
        "retrieval_config_hash": "cfg-1",
        "hard_negatives": [
            {"chunk_id": "neg-1", "document_id": "doc-a", "rank": 1},
            {"chunk_id": "neg-3", "document_id": "doc-b", "rank": 4},
        ],
        "positives": [{"chunk_id": "positive", "rank": 5}],
        "stats": {
            "citations_total": 6,
            "candidates_before_first_positive": 3,
            "hard_negatives_selected": 2,
            "dedup_dropped": 1,
        },
    }


def test_mine_hard_negatives_requires_a_retrieved_positive() -> None:
    result = mine_hard_negatives_for_case_from_trace(
        case={"reference_sources": [{"chunk_id": "missing"}]},
        trace_record={"retrieval_config_hash": "top-level", "citations": [{"chunk_id": "neg"}]},
        query_hash="query-2",
    )

    assert result["retrieval_config_hash"] == "top-level"
    assert result["hard_negatives"] == []
    assert "positives" not in result
    assert result["stats"]["candidates_before_first_positive"] == 0


def test_merge_hard_negative_records_preserves_first_ids_and_sums_stats() -> None:
    records = [
        {
            "query_hash": "query-first",
            "retrieval_config_hash": "cfg-first",
            "hard_negatives": [
                {"chunk_id": "neg-1", "document_id": "doc-a", "rank": 1},
                {"chunk_id": "neg-2", "document_id": "doc-b", "rank": 2},
            ],
            "positives": [{"chunk_id": "pos-1", "rank": 3}],
            "stats": {"citations_total": 4, "dedup_dropped": 1},
        },
        {
            "query_hash": "query-later",
            "retrieval_config_hash": "cfg-later",
            "hard_negatives": [
                {"chunk_id": "neg-1", "document_id": "doc-a", "rank": 5},
                {"chunk_id": "neg-3", "document_id": "doc-c", "rank": 1},
            ],
            "positives": [
                {"chunk_id": "pos-1", "rank": 4},
                {"chunk_id": "pos-2", "rank": 2},
            ],
            "stats": {"citations_total": 3, "candidates_before_first_positive": 2},
        },
    ]

    result = merge_hard_negative_records(records=records, max_hard_negatives=3)

    assert result["query_hash"] == "query-first"
    assert result["retrieval_config_hash"] == "cfg-first"
    assert result["hard_negatives"] == [
        {"chunk_id": "neg-1", "document_id": "doc-a", "rank": 1},
        {"chunk_id": "neg-2", "document_id": "doc-b", "rank": 2},
        {"chunk_id": "neg-3", "document_id": "doc-c", "rank": 1},
    ]
    assert result["positives"] == [
        {"chunk_id": "pos-1", "rank": 3},
        {"chunk_id": "pos-2", "rank": 2},
    ]
    assert result["stats"] == {
        "citations_total": 7,
        "candidates_before_first_positive": 2,
        "hard_negatives_selected": 3,
        "dedup_dropped": 2,
        "sources_merged": 2,
    }


def test_merge_hard_negative_records_returns_stable_empty_shape() -> None:
    assert merge_hard_negative_records(records=None) == {
        "schema": HARD_NEGATIVES_SCHEMA_V1,
        "query_hash": "",
        "retrieval_config_hash": None,
        "hard_negatives": [],
        "stats": {"sources_merged": 0, "hard_negatives_selected": 0, "dedup_dropped": 0},
    }


def test_load_hard_negatives_jsonl_skips_invalid_rows_and_dedupes(tmp_path) -> None:
    path = tmp_path / "hard-negatives.jsonl"
    rows = [
        "not-json",
        json.dumps({"schema": "wrong", "query_hash": "q", "hard_negatives": []}),
        json.dumps(
            {
                "schema": HARD_NEGATIVES_SCHEMA_V1,
                "query_hash": "q",
                "hard_negatives": [{"chunk_id": "a"}, {"chunk_id": "a"}, {"chunk_id": "b"}],
            }
        ),
        json.dumps(
            {
                "schema": HARD_NEGATIVES_SCHEMA_V1,
                "query_hash": "q",
                "hard_negatives": [{"chunk_id": "b"}, {"chunk_id": "c"}, "invalid"],
            }
        ),
        json.dumps(
            {
                "schema": HARD_NEGATIVES_SCHEMA_V1,
                "query_hash": "other",
                "hard_negatives": [{"chunk_id": "z"}],
            }
        ),
    ]
    path.write_text("\n".join(rows), encoding="utf-8")

    assert load_hard_negatives_jsonl(path) == {"q": ["a", "b", "c"], "other": ["z"]}
